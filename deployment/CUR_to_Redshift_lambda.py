import re
import boto3
import os

def getAnomalyDetectorInstance(asg_name):
	asg_client = boto3.client('autoscaling')
	json = asg_client.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])["AutoScalingGroups"][0]
	instances = []
	for i in json['Instances']:
		instances.append(i['InstanceId'])
	return instances[0]

def runCommand(commands,instances):
	runCommand = {"commands":commands,"executionTimeout":["1"]}
	ssm_client = boto3.client('ssm')
	ssm_client.send_command(InstanceIds=instances,DocumentName="AWS-RunShellScript",TimeoutSeconds=60,Parameters=runCommand)

def lambda_handler(event, context):
	s3_bucket = event['Records'][0]['s3']['bucket']['name']
	print "Bucket: " + s3_bucket
	s3_key = event['Records'][0]['s3']['object']['key']
	print "Key: " + s3_key
	
	script_commands = [
		'cd /sundaysky/',
	 	'python cost_anomaly_detector/CUR_to_Redshift.py bucket={} key={} &'.format(s3_bucket,s3_key)
	 	]

	instance = getAnomalyDetectorInstance(os.environ['anomalyASG'])
	print "Instance: " + instance
	try:
		print "INFO: Running CUR_to_Redshift"
		runCommand(script_commands,[instance])
	except:
		pass
	return "INFO: Success"
