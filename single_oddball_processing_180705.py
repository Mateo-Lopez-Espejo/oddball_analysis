import os
import io
import nems.xforms as xforms
import nems.xform_helper as xhelp
import nems_db.db as nd
import logging
import oddball_xforms as ox

''' this function/script fits and calculates SI related values considering the whole signal (no Jackknife)'''

def single_oddball_processing(cellid, batch, modelname, force_rerun=False, save_in_DB=False):
    '''

    full a oddball analisis: loads data
                             strim as rasterized point process i.e. edge or onset
                             set oddball dependent epochs
                             set jitter status epochs

                             short term plasticity
                             fir
                             dc gain shift
                             fit

                             calculates ssa index for [actual, predicted] * [f1, f2, cell]
                             calculates activiti level   ''        ''       ''  ''   ''


    :param cellid: str of cell id
    :param batch: batch number under stephen convention, default is SSA batch 296
    :param modelname: str defining the modules comprising the model.
    :param force_rerun: Bool. if true fits the model regardless of cached values, replaces cached values
    :param save_in_DB: ??? TODO what is this doing
    :return: experimetn context final_ctx. contains recordings and modelspecs
    '''

    # cellid = 'gus037d-a1'
    # batch = 296
    # modelname = 'env100pt_stp2_fir2x15_lvl1_basic-nftrial'

    log = logging.getLogger(__name__)
    batch = batch

    log.info('Initializing modelspec(s) for cell/batch {0}/{1}...'.format(
        cellid, batch))

    # parse modelname
    kws = modelname.split("_")
    # ToDo, is this good practice with the loader? it should be included in modelspec
    loader = kws[0] #'OddballLoader'
    modelspecname = "_".join(kws[1:-3])
    fitkey = kws[-3]
    est_set = kws[-2].split('-')[1]
    val_set = kws[-1].split('-')[1]


    # figure out some meta data to save in the model spec
    meta = {'batch': batch, 'cellid': cellid, 'modelname': modelname,
            'loader': loader, 'fitkey': fitkey, 'modelspecname': modelspecname,
            'username': 'svd', 'labgroup': 'lbhb', 'public': 1,
            'githash': os.environ.get('CODEHASH', ''),
            'recording': loader, 'est_set':est_set , 'val_set':val_set}

    # chekcs for caches, uses if exists, else fits de novo
    destination = '/auto/users/mateo/oddball_results/{0}/{1}/{2}/'.format(
        batch, cellid, modelname)


    if os.path.exists(destination) and force_rerun == False:
        # loads xfspecs and  final_ctx
        xfspec, ctx = xforms.load_analysis(destination, eval_model=True)

    elif not os.path.exists(destination) or force_rerun == True:
        # generate xfspec, which defines sequence of events to load data,
        # 1. Preprosesign and fit
        xfspec = list()

        # loader
        xfspec.append(['oddball_xforms.load_oddball',
                       {'cellid': cellid, 'recache': False}])

        # give oddball format: stim as rasterized point process, nan as zeros, oddball epochs, jitter status epochs,
        if loader == 'odd':
            as_point_process = True
        elif loader == 'odd1':
            as_point_process = False
        xfspec.append(['oddball_xforms.give_oddball_format', {'scaling': 'same', 'as_point_process': as_point_process}])

        # define model architecture
        xfspec.append(['nems.xforms.init_from_keywords',
                       {'keywordstring': modelspecname, 'meta': meta}])

        # masks by jitter status
        xfspec.append(['oddball_xforms.mask_by_jitter', {'Jitter_set': est_set}])

        # adds jackknife, fitter and prediction
        log.info("n-fold fitting...")
        tfolds = 5
        xfspec.append(['nems.xforms.mask_for_jackknife',
                       {'njacks': tfolds, 'epoch_name': 'TRIAL'}])

        ## caches the fitted values, so they can be reused for different validations
        midway_cache = '/auto/users/mateo/oddball_results/{0}/{1}/{2}/'.format(
                        batch, cellid, modelname.rsplit('_', 1)[0])
        if os.path.exists(midway_cache) and force_rerun == False:
            # loads xfspecs and  final_ctx
            xfspec, ctx = xforms.load_analysis(midway_cache,
                                               eval_model=True)

        elif not os.path.exists(midway_cache) or force_rerun == True:
            # adds fitter
            xfspec.append(['nems.xforms.fit_nfold', {}])

            # evaluates for chaching
            ctx, log_xf = xforms.evaluate(xfspec)

            modelspecs = ctx['modelspecs']
            modelspecs[0][0]['meta']['modelpath'] = midway_cache
            modelspecs[0][0]['meta']['figurefile'] = midway_cache + 'figure.0000.png'

            # save results
            log.info('Saving modelspec(s) to {0} ...'.format(midway_cache))
            ox.save_analysis(midway_cache,
                                 recording=ctx['rec'],
                                 modelspecs=modelspecs,
                                 xfspec=xfspec,
                                 figures=None,
                                 log=log_xf)

        # sets validation mask
        xfspec.append(['oddball_xforms.mask_by_jitter', {'Jitter_set': val_set}])

        # adds predictor
        xfspec.append(['nems.xforms.predict', {}])


        # add metrics correlation
        xfspec.append(['nems.analysis.api.standard_correlation', {},
                       ['est', 'val', 'modelspecs', 'rec'], ['modelspecs']])

        # adds sumary plots ToDo i dont like this plotting, but is necesary to user Save analysis
        xfspec.append(['nems.xforms.plot_summary',    {}])

        #### evaluates preprocessing and fitting ####
        ctx, log_xf = xforms.evaluate(xfspec,ctx, start=-4, stop=None)

        # caches analisys
        modelspecs = ctx['modelspecs']
        modelspecs[0][0]['meta']['modelpath'] = destination
        modelspecs[0][0]['meta']['figurefile'] = destination + 'figure.0000.png'

        # save results Todo figure out the good way of saving stuff
        log.info('Saving modelspec(s) to {0} ...'.format(destination))
        xforms.save_analysis(destination,
                             recording=ctx['rec'],
                             modelspecs=modelspecs,
                             xfspec=xfspec,
                             figures=ctx['figures'],
                             log=log_xf)
    else:
        raise SystemError("WTF just happened? contact Mateo")


    # add SSA related metrics
    # val, modelspecs, sub_epoch, super_epoch, baseline
    jitters = ['Jitter_On', 'Jitter_Off', 'Jitter_Both']
    xfspec.append(['oddball_xforms.calculate_oddball_metrics',
                   {'sub_epoch': 'Stim', 'super_epoch': jitters, 'baseline': 'silence'},
                   ['val', 'modelspecs'], ['modelspecs']])

    # evaluate the last step.
    ctx, log_xf = xforms.evaluate(xfspec, ctx, start =-1 , stop=None)


    # re-saves overwriting modelspecs containing the SSA related metrics,
    modelspecs = ctx['modelspecs']
    log.info('Saving modelspec(s) to {0} ...'.format(destination))
    xforms.save_analysis(destination,
                         recording=ctx['rec'],
                         modelspecs=modelspecs,
                         xfspec=xfspec,
                         figures=ctx['figures'],
                         log=log_xf)

    if save_in_DB:
        # save in database as well TODO why is saving as single element of modelspec?
        nd.update_results_table(modelspecs[0], preview=None,
                                username="MLE", labgroup="lbhb")

    return ctx


'''
testing suit

cellid = 'gus037d-a2'
modelname = 'stp2_fir2x15_lvl1_basic-nftrial'
single_oddball_processing(cellid=cellid, modelname=modelname, force_refit=False, save_in_DB = False)
'''
