#!/usr/bin/env python3
"""
Created on Wed Dec 22 15:51:51 2021
@author: eduardoaraujo
"""

import pandas as pd 
import numpy as np 
import copy
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from datetime import datetime, timedelta
from get_data import *
from sqlalchemy import create_engine
from loguru import logger

logger.add("/var/log/forecast.log", retention="7 days")

engine = create_engine("postgresql://epigraph:epigraph@localhost:5432/epigraphhub")


def lgbm_model(alpha = 0.5, params=None, **kwargs):
    '''
    Return an LGBM model
    :param kwargs:
    :return: LGBMRegressor model
    '''
    if params is None:
        params = {
            'n_jobs': 8,
            'max_depth': 4,
            'max_bin': 63,
            'num_leaves': 255,
#             'min_data_in_leaf': 1,
            'subsample': 0.9,
            'n_estimators': 200,
            'learning_rate': 0.1,
            'colsample_bytree': 0.9,
            'boosting_type': 'gbdt'
        }

    model = lgb.LGBMRegressor(objective='quantile', alpha = alpha, **params)

    return model 


def rolling_predictions(target_name, data,hosp_as_predict, ini_date = '2020-03-01',split = 0.25, horizon_forecast = 14, maxlag=14):

    target = data[target_name]

    if hosp_as_predict == False: 

        for i in data.columns:

            if i.startswith('hosp') == True:
                data = data.drop(i, axis = 1)

    df_lag = build_lagged_features(copy.deepcopy(data), maxlag=maxlag )

    #print(type(df_lag.index[0]))
    #print(target.index[0])

    ini_date = max(df_lag.index[0],target.index[0], datetime.strptime(ini_date, "%Y-%m-%d"))

    df_lag = df_lag[ini_date:]
    target = target[ini_date:]
    df_lag = df_lag.dropna()

    # remove the target column and columns related with the day that we want to predict 
    df_lag = df_lag.drop(data.columns, axis = 1)

    # targets 
    targets = {}

    for T in np.arange(1,horizon_forecast+1,1):
        if T == 1:
            targets[T] = target.shift(-(T - 1))
        else:
            targets[T] = target.shift(-(T - 1))[:-(T - 1)]
#         print(T, len(df_lag), len(fit_target))
#         print(df_lag.index,fit_target.index)

    X_train, X_test, y_train, y_test = train_test_split(df_lag, target, train_size=split, test_size=1 - split, shuffle=False)

    # predictions 
    preds5 = np.empty((len(df_lag), horizon_forecast))
    preds50 = np.empty((len(df_lag), horizon_forecast))
    preds95 = np.empty((len(df_lag), horizon_forecast))

    #forecasts5 = []
    #forecasts50 = []
    #forecasts95 = []

    for T in range(1, horizon_forecast + 1):

        tgt = targets[T][:len(X_train)]

        #tgtt = targets[T][len(X_train)]
        model5 = lgbm_model(alpha = 0.025)
        model50 = lgbm_model(alpha = 0.5)
        model95 = lgbm_model(alpha = 0.975)

        model5.fit(X_train, tgt)
        model50.fit(X_train, tgt)
        model95.fit(X_train, tgt)

        #dump(model, f'saved_models/{estimator}_{target_name}_{T}.joblib')

        pred5 = model5.predict(df_lag.iloc[:len(targets[T])])
        pred50 = model50.predict(df_lag.iloc[:len(targets[T])])
        pred95 = model95.predict(df_lag.iloc[:len(targets[T])])

        dif = len(df_lag) - len(pred5)
        if dif > 0:
            pred5 = list(pred5) + ([np.nan] * dif)

        dif = len(df_lag) - len(pred50)
        if dif > 0:
            pred50 = list(pred50) + ([np.nan] * dif)

        dif = len(df_lag) - len(pred95)
        if dif > 0:
            pred95 = list(pred95) + ([np.nan] * dif)

        preds5[:, (T - 1)] = pred5
        preds50[:, (T - 1)] = pred50
        preds95[:, (T - 1)] = pred95

        #forecast5 = model5.predict(df_lag.iloc[-1:])
        #forecast50 = model50.predict(df_lag.iloc[-1:])
        #forecast95 = model95.predict(df_lag.iloc[-1:])

        #forecasts5.append(forecast5)
        #forecasts50.append(forecast50)
        #forecasts95.append(forecast95)


    # transformando preds em um array
    train_size = len(X_train)
    point = targets[1].index[train_size]

    pred_window = preds5.shape[1]
    llist = range(len(targets[1].index) - (preds5.shape[1]))

    y5 = []
    y50 = []
    y95 = []

    x=[]
    for n in llist:
        x.append(targets[1].index[n + pred_window])
        y5.append(preds5[n][-1])
        y50.append(preds50[n][-1])
        y95.append(preds95[n][-1])

    #forecast_dates = []

    #last_day = datetime.strftime(np.array(x)[-1], '%Y-%m-%d')

    #a = datetime.strptime(last_day, '%Y-%m-%d')

    #for i in np.arange(1, horizon_forecast + 1):

     #   d_i = datetime.strftime(a+timedelta(days=int(i)),'%Y-%m-%d' ) 

      #  forecast_dates.append(datetime.strptime(d_i, '%Y-%m-%d'))

    return np.array(x), np.array(y5),np.array(y50), np.array(y95),  targets[1], len(X_train)#, forecast_dates, np.array(forecasts5)[:,0], np.array(forecasts50)[:,0],np.array(forecasts95)[:,0]

def make_single_prediction(target_curve_name, canton, predictors, vaccine = True, smooth= True, hosp_as_predict = False,ini_date = '2020-03-01', title = None, updated_data = True):

    '''
    Function to make single prediction 
    
    Important: 
    * By default the function is using the clustering cantons and the data since 2020
    * For the predictor hospCapacity is used as predictor the column ICU_Covid19Patients
    
    params canton: canton of interest 
    params predictors: variables that  will be used in model 
    params vaccine: It determines if the vaccine data from owid will be used or not 
    params smooth: It determines if data will be smoothed or not 
    params hosp_as_predict: It determines if hosp cruves will be use as predictors or not 
    params ini_date: Determines the beggining of the train dataset
    params title: If none the title will be: Hospitalizations - canton
    params path: If none the plot will be save in the directory: images/hosp_{canton}
    '''

    # compute the clusters 
    clusters, all_regions,fig = compute_clusters('cases', t=0.8, plot = False)

    for cluster in clusters:

        if canton in cluster:

            cluster_canton = cluster


    # getting the data 
    df = get_combined_data(predictors, cluster_canton, vaccine=vaccine, smooth = smooth)
    # filling the nan values with 0
    df = df.fillna(0)
    
    if updated_data: 
        # atualizando a coluna das Hospitalizações com os dados mais atualizados
        df_new = get_updated_data(smooth)
    
        df.loc[df_new.index[0]: df_new.index[-1], 'hosp_GE'] = df_new.hosp_GE

        # utilizando como último data a data dos dados atualizados:
        df = df.loc[:df_new.index[-1]]

    # apply the model 

    target_name = f'{target_curve_name}_{canton}'

    horizon = 14
    maxlag = 14

    # get predictions and forecast 
    #date_predsknn, predsknn, targetknn, train_size, date_forecastknn, forecastknn = rolling_predictions(model_knn, 'knn', target_name, df , ini_date = '2021-01-01',split = 0.75,   horizon_forecast = horizon, maxlag=maxlag,)
    x, y5,y50, y95,  target,train_size  = rolling_predictions(target_name, df , hosp_as_predict,  ini_date = ini_date,split = 0.75,   horizon_forecast = horizon, maxlag=maxlag)

    #fig = plot_predictions(target_curve_name, canton, target, train_size, x, y5,y50, y95, forecast_dates, forecasts5, forecasts50,forecasts95, title, path)

    df = pd.DataFrame()
    df['target'] = target[14:]
    df['date'] = x
    df['lower'] = y5
    df['median'] = y50
    df['upper'] = y95
    df['train_size'] = [train_size-14]*len(df)
    return df 

def make_predictions_all_cantons(target_curve_name,  predictors, vaccine = True, smooth= True, hosp_as_predict = False,ini_date = '2020-03-01', title = None):

    '''
    Function to make prediction for all the cantons
    
    Important: 
    * By default the function is using the clustering cantons and the data since 2020
    * For the predictor hospCapacity is used as predictor the column ICU_Covid19Patients
    
    params target_curve_name: string to indicate the target column of the predictions
    params predictors: variables that  will be used in model 
    params vaccine: It determines if the vaccine data from owid will be used or not 
    params smooth: It determines if data will be smoothed or not 
    params hosp_as_predict: It determines if hosp cruves will be use as predictors or not 
    params ini_date: Determines the beggining of the train dataset
    
    returns: Dataframe with the predictions for all the cantons
    '''
    
    df_all = pd.DataFrame()

    # compute the clusters 
    clusters, all_regions,fig = compute_clusters('cases', t=0.8, plot = False)

    for cluster in clusters:
        # getting the data 
        df = get_combined_data(predictors, cluster, vaccine=vaccine, smooth = smooth)
        # filling the nan values with 0
        df = df.fillna(0)
    
        for canton in cluster:
            # apply the model 

            target_name = f'{target_curve_name}_{canton}'

            horizon = 14
            maxlag = 14

            # get predictions and forecast 
            #date_predsknn, predsknn, targetknn, train_size, date_forecastknn, forecastknn = rolling_predictions(model_knn, 'knn', target_name, df , ini_date = '2021-01-01',split = 0.75,   horizon_forecast = horizon, maxlag=maxlag,)
            x, y5,y50, y95,  target,train_size = rolling_predictions(target_name, df , hosp_as_predict,  ini_date = ini_date,split = 0.75,   horizon_forecast = horizon, maxlag=maxlag)
            
            #fig = plot_predictions(target_curve_name, canton, target, train_size, x, y5,y50, y95, forecast_dates, forecasts5, forecasts50,forecasts95, title, path)

            df_pred = pd.DataFrame()
            df_pred['target'] = target[14:]
            df_pred['date'] = x
            df_pred['lower'] = y5
            df_pred['median'] = y50
            df_pred['upper'] = y95
            df_pred['train_size'] = [train_size-14]*len(df_pred)
            df_pred['canton'] = [canton]*len(df_pred)
            
            df_all = pd.concat([df_all,df_pred])
            
    return df_all

def rolling_forecast(target_name, data, hosp_as_predict, ini_date, horizon_forecast = 14, maxlag=14):
    
    target = data[target_name]

    if hosp_as_predict == False: 

        for i in data.columns:

            if i.startswith('hosp') == True:
                data = data.drop(i, axis = 1)

    df_lag = build_lagged_features(copy.deepcopy(data), maxlag=maxlag )

    ini_date = max(df_lag.index[0],target.index[0], datetime.strptime(ini_date, "%Y-%m-%d"))

    df_lag = df_lag[ini_date:]
    target = target[ini_date:]
    df_lag = df_lag.dropna()


    # remove the target column and columns related with the day that we want to predict 
    df_lag = df_lag.drop(data.columns, axis = 1)


    # targets 
    targets = {}

    for T in np.arange(1,horizon_forecast+1,1):
        if T == 1:
            targets[T] = target.shift(-(T - 1))
        else:
            targets[T] = target.shift(-(T - 1))[:-(T - 1)]
#         print(T, len(df_lag), len(fit_target))
#         print(df_lag.index,fit_target.index)


    # forecast
    forecasts5 = []
    forecasts50 = []
    forecasts95 = []

    for T in range(1, horizon_forecast + 1):
        # training of the model with all the data available

        model5 = lgbm_model(alpha = 0.025)
        model50 = lgbm_model(alpha = 0.5)
        model95 = lgbm_model(alpha = 0.975)

        # eliminando os últimos 3 dias de dados 
        model5.fit(df_lag.iloc[:len(targets[T])-3], targets[T][:-3])
        model50.fit(df_lag.iloc[:len(targets[T])-3], targets[T][:-3])
        model95.fit(df_lag.iloc[:len(targets[T])-3], targets[T][:-3])

        # make the forecast 
        forecast5 = model5.predict(df_lag.iloc[-1:])
        forecast50 = model50.predict(df_lag.iloc[-1:])
        forecast95 = model95.predict(df_lag.iloc[-1:])


        forecasts5.append(forecast5)
        forecasts50.append(forecast50)
        forecasts95.append(forecast95)


    # transformando preds em um array

    forecast_dates = []

    last_day = datetime.strftime((df_lag.index)[-1], '%Y-%m-%d')

    a = datetime.strptime(last_day, '%Y-%m-%d')

    for i in np.arange(1, horizon_forecast + 1):

        d_i = datetime.strftime(a+timedelta(days=int(i)),'%Y-%m-%d' ) 

        forecast_dates.append(datetime.strptime(d_i, '%Y-%m-%d'))

    return targets[1], forecast_dates, np.array(forecasts5)[:,0], np.array(forecasts50)[:,0], np.array(forecasts95)[:,0]


def make_forecast(target_curve_name, canton, predictors, vaccine = True, smooth= True, hosp_as_predict = False,ini_date = '2020-03-01', title = None, updated_data = True):

    # compute the clusters 
    clusters, all_regions,fig = compute_clusters('cases', t=0.8, plot = False)

    for cluster in clusters:

        if canton in cluster:

            cluster_canton = cluster


    # getting the data 
    df = get_combined_data(predictors, cluster_canton, vaccine=vaccine, smooth = smooth)
    # filling the nan values with 0
    df = df.fillna(0)

    if updated_data:
        # atualizando a coluna das Hospitalizações com os dados mais atualizados
        df_new = get_updated_data(smooth)
    
        df.loc[df_new.index[0]: df_new.index[-1], 'hosp_GE'] = df_new.hosp_GE
    
        # utilizando como último data a data dos dados atualizados:
        df = df.loc[:df_new.index[-1]]


    # apply the model 

    target_name = f'{target_curve_name}_{canton}'

    horizon = 14
    maxlag = 14

    # get predictions and forecast 
    #date_predsknn, predsknn, targetknn, train_size, date_forecastknn, forecastknn = rolling_predictions(model_knn, 'knn', target_name, df , ini_date = '2021-01-01',split = 0.75,   horizon_forecast = horizon, maxlag=maxlag,)
    ydata, dates_forecast, forecast5, forecast50, forecast95 = rolling_forecast(target_name, df, hosp_as_predict = hosp_as_predict, ini_date = ini_date,  horizon_forecast = horizon, maxlag=maxlag)

    #fig = plot_forecast(target_curve_name, canton, ydata, dates_forecast, forecast5, forecast50, forecast95)

    df = pd.DataFrame()

    df['date'] = dates_forecast
    df['lower'] = forecast5
    df['median'] = forecast50
    df['upper'] = forecast95
    return df 

def make_forecast_all_cantons(target_curve_name, predictors, vaccine = True, smooth= True, hosp_as_predict = False,ini_date = '2020-03-01', title = None):
    '''
    Function to make the forecast for all the cantons
    
    Important: 
    * By default the function is using the clustering cantons and the data since 2020
    * For the predictor hospCapacity is used as predictor the column ICU_Covid19Patients
    
    params target_curve_name: string to indicate the target column of the predictions
    params predictors: variables that  will be used in model 
    params vaccine: It determines if the vaccine data from owid will be used or not 
    params smooth: It determines if data will be smoothed or not 
    params hosp_as_predict: It determines if hosp cruves will be use as predictors or not 
    params ini_date: Determines the beggining of the train dataset
    
    returns: Dataframe with the forecast for all the cantons
    '''
    df_all = pd.DataFrame()
    
    # compute the clusters 
    clusters, all_regions,fig = compute_clusters('cases', t=0.8, plot = False)

    for cluster in clusters:

        # getting the data 
        df = get_combined_data(predictors, cluster, vaccine=vaccine, smooth = smooth)
        # filling the nan values with 0
        df = df.fillna(0)
        
        for canton in cluster:

            # apply the model 

            target_name = f'{target_curve_name}_{canton}'

            horizon = 14
            maxlag = 14

            # get predictions and forecast 
            #date_predsknn, predsknn, targetknn, train_size, date_forecastknn, forecastknn = rolling_predictions(model_knn, 'knn', target_name, df , ini_date = '2021-01-01',split = 0.75,   horizon_forecast = horizon, maxlag=maxlag,)
            ydata, dates_forecast, forecast5, forecast50, forecast95 = rolling_forecast(target_name, df, hosp_as_predict = hosp_as_predict, ini_date = ini_date,  horizon_forecast = horizon, maxlag=maxlag)

            #fig = plot_forecast(target_curve_name, canton, ydata, dates_forecast, forecast5, forecast50, forecast95)

            df_for = pd.DataFrame()

            df_for['date'] = dates_forecast
            df_for['lower'] = forecast5
            df_for['median'] = forecast50
            df_for['upper'] = forecast95
            df_for['canton'] = [canton]*len(df_for)

            df_all= pd.concat([df_all, df_for])
        
    return df_all 

@logger.catch
def save_to_database(df, table_name):
    df.to_sql(table_name, engine, schema= 'switzerland', if_exists = 'replace')

if __name__ == '__main__':
    #target_curve_name = 'hosp'
    canton = 'GE'
    predictors = ['cases', 'hosp', 'test', 'hospcapacity']

    # compute the predictions in sample and out sample for validation 
    df_val_hosp_up = make_single_prediction('hosp', canton, predictors, vaccine = True, smooth= True, hosp_as_predict = True ,ini_date = '2020-03-01', title = None, updated_data = True)
    df_val_icu = make_single_prediction('ICU_patients', canton, predictors, vaccine = True, smooth= True, hosp_as_predict = True,ini_date = '2020-03-01', title = None, updated_data = False)
    df_val_hosp_cantons = make_predictions_all_cantons('hosp',  predictors, vaccine = True, smooth= True, hosp_as_predict = False,ini_date = '2020-03-01', title = None)
    df_val_icu_cantons = make_predictions_all_cantons('ICU_patients',  predictors, vaccine = True, smooth= True, hosp_as_predict = False,ini_date = '2020-03-01', title = None)

    logger.info('Generated validation prediction tables')


    # compute the forecast
    df_for_hosp = make_forecast('hosp', canton, predictors, vaccine = True, smooth= True, hosp_as_predict = True,ini_date = '2020-03-01', title = None, updated_data = False)
    df_for_icu = make_forecast('ICU_patients', canton, predictors, vaccine = True, smooth= True, hosp_as_predict = True,ini_date = '2020-03-01', title = None, updated_data = False)
    df_for_hosp_cantons = make_forecast_all_cantons('hosp',  predictors, vaccine = True, smooth= True, hosp_as_predict = False,ini_date = '2020-03-01', title = None)
    df_for_icu_cantons = make_forecast_all_cantons('ICU_patients',  predictors, vaccine = True, smooth= True, hosp_as_predict = False,ini_date = '2020-03-01', title = None)

    df_for_hosp_up = make_forecast('hosp', canton, predictors, vaccine = True, smooth= True, hosp_as_predict = True,ini_date = '2020-03-01', title = None,updated_data = True)
    
    logger.info('Finished running forecasts')


    # save the datasets 
    # df_val_hosp_up.to_sql('ml_validation_hosp_up', engine, schema= 'switzerland', if_exists = 'replace')
    save_to_database(df_val_hosp_up, 'ml_validation_hosp_up')
    
    save_to_database(df_val_hosp_cantons, 'ml_val_hosp_all_cantons')
    # df_val_icu.to_sql('ml_validation_icu', engine, schema= 'switzerland', if_exists = 'replace')
    save_to_database(df_val_icu,'ml_validation_icu')
    save_to_database(df_val_icu_cantons, 'ml_val_icu_all_cantons')
    
    # df_for_hosp.to_sql('ml_forecast_hosp', engine, schema= 'switzerland', if_exists = 'replace') 
    save_to_database(df_for_hosp,'ml_forecast_hosp')
    save_to_database(df_for_hosp_cantons, 'ml_for_hosp_all_cantons')
    # df_for_icu.to_sql('ml_forecast_icu', engine, schema= 'switzerland', if_exists = 'replace') 
    save_to_database(df_for_icu,'ml_forecast_icu')
    save_to_database(df_for_icu_cantons, 'ml_for_icu_all_cantons')
    # df_for_hosp_up.to_sql('ml_forecast_hosp_up', engine, schema= 'switzerland', if_exists = 'replace')
    save_to_database(df_for_hosp_up,'ml_forecast_hosp_up')
    
    logger.info('Data saved to DB')