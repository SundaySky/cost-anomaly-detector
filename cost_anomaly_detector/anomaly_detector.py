import psycopg2
import pandas as pd
from datetime import datetime,timedelta
import numpy as np
from os import path,makedirs
import sys
import yaml


#%%
def modify_queries(params):
	by_region_queries = {}
	for query_name, query_params in params['queries'].iteritems():
		# Change keys to lower, change tags to user_tags
		modified_query = query_params.copy()
		modified_query = dict((k.lower(), v) for k, v in modified_query.iteritems())
		for key in modified_query.keys():
			if key not in ['region','service','operation']:
				modified_query['user_'+key] = modified_query.pop(key)
		# Modify by-region queries
		if 'region' in modified_query:
			temp_query = {}
			if modified_query['region'] == 'all':
				for region in params['aws_query_regions']:
					temp_query = modified_query.copy()
					temp_query['region'] = region
					by_region_queries[query_name+'_'+region] = temp_query
				# add general query
				general_query = temp_query.copy()
				del[general_query['region']]
				by_region_queries[query_name+'_'+'general'] = general_query
			elif ',' in modified_query['region']:
				regions = modified_query['region'].split(',')
				for region in regions:
					region = region.strip()
					temp_query = modified_query.copy()
					temp_query['region'] = region
					by_region_queries[query_name+'_'+region] = temp_query
				# add general query
				general_query = temp_query.copy()
				del[general_query['region']]
				by_region_queries[query_name+'_'+'general'] = general_query
		else:
			by_region_queries[query_name] = modified_query
	return by_region_queries

def run_detector(queries, params):
	LOG_FOLDER = params['log_folder']
	log_file = 'anomaly_detector_results_'+params['date']+'.txt'
	log_file_path = path.join(LOG_FOLDER,log_file)
	if path.exists(log_file_path):
		print "Log file already exist, exiting."
		return
	if not path.exists(LOG_FOLDER):
		makedirs(LOG_FOLDER)
	
	fix_column_names = lambda x : x.replace(':','_').replace(' ','_').lower()
	queries = {k:dict((fix_column_names(c),v[c]) for c in v) for k,v in queries.items()}
	df = fetch_data(params)
	df.columns = map(fix_column_names, df.columns)
	df['region'] = df['region'].apply(parse_region)
	print 'DataFrame columns: ' + ', '.join(df.columns.tolist())
	out_file = open(log_file_path,'w')
	for query in queries:
		print '_'*70
		print query
		d = set(queries[query].keys()).difference(df.columns) 
		if len(d) > 0:
			print "fields " + str(list(d)) + " are not in the dataframe."
			continue
		df_query = build_query_df(df,queries[query])
		
		if df_query.empty:
			print "No data exist for this query"
			continue
		
		if params['date'] not in df_query.index:
			print 'No data exist for the date %s' % (params['date'],)
			continue
				
		anomaly = find_anomalies(df_query,params)
		if (anomaly['Mean'][0]==0 and anomaly['Std'][0]==0 and anomaly['cost'][0]==0):
			continue
		
		anomaly['service'] = query
		write_anomalies_to_db(anomaly,params)
		out_file.write(out_file_format(anomaly))
		
#%%
def out_file_format(df):
	return df.apply(lambda x:map(lambda v:x.name+'='+str(v),x),axis=0).to_csv(index=False, header=False)

#%%
def write_anomalies_to_db(anomalies,params):
	sql_query = "INSERT INTO awsbilling_anomalies (anomaly_date,service,score,isanomaly,daily_cost,mean_cost,std_cost) values(\'%s\', \'%s\', %s, %s, %s, %s, %s)"
	try:
		print "connecting to db"
		con=psycopg2.connect(dbname=params['redshift_db_name'], host=params['redshift_hostname'], port='5439', user=params['redshift_user'], password=params['redshift_password'])
		con.autocommit = True
		print "creating cursor"
		cur = con.cursor()
		print "running command"
		anomalies.apply(lambda x:cur.execute(sql_query % (x['day'],x['service'],x['score'],x['is_anomaly'], x['cost'], x['Mean'], x['Std'])),axis=1)
		cur.close()
		con.close()
		print "Done"
	except Exception as e:
		print "failed connecting to DB"
		raise e

#%%
def parse_region(usagetype):
	regions = {'USW1':'us-west-1', 'USW2':'us-west-2', 'APN1':'ap-northeast-1', 'EUW2':'eu-west-2', 'EUW1':'eu-west-1'}
	for k,v in regions.items():
		if usagetype.startswith(k):
			return v
	return 'us-east-1'
#%%        
def build_query_df(df,query):
	query_str = ' and '.join([k+'==\''+v+'\'' for k,v in query.items() if '*' not in v])    
	query_str +=  (' and ' + ' and '.join(['\''+v.replace('*','')+'\' in '+k for k,v in query.items() if '*' in v])) if '*' in ''.join(query.values()) else ''
	print query_str
		
	return df.query(query_str)[['day','cost']].groupby('day').sum()
#%%
def fetch_tags(table,params):
	sql_query = 'select remappedusertag, usertag from %s' % table
	results = fetch_db_data(sql_query,params)
	return pd.DataFrame(results,columns=['remappedusertag', 'usertag'])
#%%
def fetch_data(params):
	table_name_prefix = 'AWSBilling'
	tags_suffix = '_tagmapping'
	history_period_days = params['history_period_days']
	date = params['date']
	date = datetime.strptime(date,'%Y-%m-%d')
	months_to_query = set([date.strftime('%Y%m')])
	months_to_query.add((date-timedelta(days=history_period_days)).strftime('%Y%m'))
	df_all_data = pd.DataFrame()
	for m in months_to_query:
		print "querying table: " + table_name_prefix + m
		tags_df = fetch_tags(table_name_prefix + m + tags_suffix, params)
		print tags_df
		df_all_data = df_all_data.append(run_single_query(table_name_prefix + m, tags_df, params))
	return df_all_data
#%%
def run_single_query(table_name,tags_df,params):
	tags_str = ',' + ', '.join (tags_df.apply(lambda x:x[0],axis=1))
	aws_account = ''
	if 'aws_account' in params:
		if type(params['aws_account']) == list:
			for account in params['aws_account']:
				aws_account += '\''+str(account)+'\','
			aws_account = aws_account[:-1]
		else:
			aws_account = '\''+str(params['aws_account'])+'\''
	else:
		aws_account = '\'\''
	sql_query = 'select SUBSTRING(identity_timeinterval,1,10) as day , lineitem_productcode as service, SUM(lineitem_unblendedcost) as cost, \
					 lineitem_operation as operation, Product_usagetype as region %s \
					  from %s \
					  where lineitem_lineitemtype not ilike \'RIFee\'\
					  and lineitem_lineitemtype not ilike \'Fee\'\
					  and lineitem_lineitemtype not ilike \'Refund\'\
					  and lineitem_lineitemtype not ilike \'credit\'\
					  and (lineitem_usageaccountid IN (%s) OR %s <= 2)\
					  group by day, lineitem_productcode, lineitem_operation, Product_usagetype %s' % (tags_str,table_name,aws_account,str(len(aws_account)),tags_str)
	results = fetch_db_data(sql_query,params)
	df = pd.DataFrame(results, columns = ['day','service','cost','operation','region'] + list(tags_df['usertag']))
	df['day'] = pd.to_datetime(df['day'])
	return df
	
#%%
def fetch_db_data(sql_query,params):
	try:
		con=psycopg2.connect(dbname=params['redshift_db_name'], host=params['redshift_hostname'], port='5439', user=params['redshift_user'], password=params['redshift_password'])
		con.autocommit = False        
		cur = con.cursor()
		cur.execute(sql_query)        
		results = cur.fetchall()
		cur.close()
		con.close()
		return results
	except Exception as e:
		print "failed connecting to DB"
		raise e
#%%
def find_anomalies(data,params):
	data.cost.interpolate(inplace=True)
	end = datetime.strptime(params['date'],'%Y-%m-%d')
	start = end - timedelta(days=int(params['history_period_days'])+1)
	data = data[start:end]
	
	data = data.astype(float)
	current_cost = data.loc[end].cost
	data = data.drop([end,end-timedelta(days=1)])
	std = data.cost.std()
	mean = data.cost.mean()
	
	events = pd.DataFrame({'day':params['date'],
						   'score':max(0,min((current_cost - mean)/std if std>0 else 0,100)),
						   'is_anomaly':int(current_cost >= mean+float(params['threshold_std'])*std and current_cost > float(params['threshold_relative'])* mean and current_cost >= float(params['threshold_absolute'])),
						   'cost':current_cost,
						   'Mean':mean,
						   'Std':std,
						   }, index = [end])
	return events
#%%
def get_kwargs(arguments):
	args = {}
	for line in arguments:
		try:
			if line.startswith('#') or line=='':
				continue
			k,v = line.split('=',1)
			args[k.strip()] = v.strip()
		except Exception:
			pass
	return args

#%% main
if __name__ == '__main__':
	# read params
	params = {}
	params['date'] = datetime.strftime(datetime.now() - timedelta(days=2), '%Y-%m-%d')
	# override params with conf file
	with open(path.dirname(__file__)+'/CAD_conf.yml','r') as conf_file:
		params.update(yaml.load(conf_file))
	# override params with arguments
	params.update(get_kwargs(sys.argv))
	# modify per region queries
	params['queries'] = modify_queries(params)
	
	run_detector(params['queries'],params)
