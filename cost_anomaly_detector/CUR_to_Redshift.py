import boto3
import re
import os
import psycopg2
import sys
import logging
from datetime import datetime
import yaml

# Set logging
LOG_FOLDER = r'/sundaysky/logs/CUR_to_Redshift/'
date = datetime.now().strftime("%Y-%m-%d")
log_file = 'CUR_to_Redshift_'+date+'.log'
log_file_path = os.path.join(LOG_FOLDER,log_file)
if os.path.exists(log_file_path):
	pass
if not os.path.exists(LOG_FOLDER):
	os.makedirs(LOG_FOLDER)
logging.basicConfig(filename=log_file_path, level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
logging.getLogger("boto3").setLevel(logging.ERROR)

# get parameters
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

# read conf file
params = {}
with open(os.path.dirname(__file__)+'/CAD_conf.yml','r') as conf_file:
	params.update(yaml.load(conf_file))
# override conf with arguments
params.update(get_kwargs(sys.argv))

logging.debug('parameters: '+str(params))

s3 = boto3.resource('s3')

logging.info('S3 bucket: '+params['bucket'])
logging.info('S3 key: '+params['key'])

# Get the SQL commands
bucket = s3.Bucket(params['bucket'])
s3_file_object = s3.Object(params['bucket'],params['key'])

# Edit the SQL query
sql_query = s3_file_object.get()['Body'].read()
logging.debug('Original SQL query: '+sql_query)

sql_query = re.compile('(<S3_BUCKET_REGION>)').sub("'" + params['s3_aws_region'] + "'",sql_query,0)
sql_query = re.compile('(<AWS_ROLE>)').sub(params['redshift_role'],sql_query,0)
sql_query = re.compile('Amount VARCHAR\(512\)').sub('Amount DECIMAL(50,10)',sql_query,0)
sql_query = re.compile('lendedCost VARCHAR\(512\)').sub('lendedCost DECIMAL(50,10)',sql_query,0)
logging.debug('Modified SQL query: '+sql_query)

regex = re.search('create table (.+?)\(', sql_query)
table_name = regex.group(1)

# Drop old tables and create the new ones
try:
	print "connecting to db"
	logging.info("connecting to db")
	con=psycopg2.connect(dbname=params['redshift_db_name'], host=params['redshift_hostname'], port='5439', user=params['redshift_user'], password=params['redshift_password'])
	con.autocommit = True
	print "creating cursor"
	logging.debug("creating cursor")
	cur = con.cursor()
	print "dropping table if exists"
	logging.info("dropping table if exists")
	cur.execute("DROP table if exists " + table_name)
	cur.execute("DROP table if exists " + table_name + "_tagmapping")
	print "creating table"
	logging.info("creating table: "+table_name)
	cur.execute(sql_query)
	if 'redshift_table_permitted_users' in params:
		print "grant access"
		logging.info("granting access to users")
		cur.execute("GRANT SELECT ON {} TO {}".format(table_name,params['redshift_table_permitted_users']))
		cur.execute("GRANT SELECT ON {}_tagmapping TO {}".format(table_name,params['redshift_table_permitted_users']))
	con.commit()
	cur.close()
	con.close()
except Exception as e:
	print "failed connecting to DB"
	logging.error("failed connecting to DB")
	raise e
	logging.error(e)

logging.info("Running anomaly_detector.py")
os.system('python /sundaysky/cost_anomaly_detector/anomaly_detector.py')
logging.info("Done running anomaly_detector.py")
