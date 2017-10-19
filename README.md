# AWS Cost Anomaly Detector (CAD)

## Background
AWS’s pay-for-what-you-use policy is one of its great advantages, but it can also be dangerous – a bug or high traffic might cause unexpected billing.  
The “aws cost anomaly detector” is a product made to keep track of your aws account billing and notify you whenever you pay more than expected.

The anomaly detector has 2 main functions:
* Writing the billing data to RedShift
* Finding billing anomalies


### General Flow
* Whenever a new CUR is uploaded to your billing bucket a lambda is triggered
* The lambda issues a command to the anomaly detector instance 
* The instance creates a Redshift table and writes the CUR data to it
* After the data is written, the instance runs the anomaly detection algorithm and writes the results


### Infrastructure Overview
* Billing S3 bucket
	* With CURs
* Redshift database
	* With awsbilling_anomalies table
* A Lambda function
	* Triggered by new CUR in the billing bucket and initiates the job on the instance
* An Auto Scaling Group
	* The anomaly detector instance is started from an autoscaling group and gets all configuration on startup. This makes the service redundant and easly mantainable.  
	  We reccomendend to have only one instance up at a time, otherwise each run would be randomly assigned to one of the active instances.
* An anomaly detector instance (t2.micro)
	* To write the data and detect the anomalies (the process takes too long to run with a lambda function)


### Algorithem
In order to detect anomalies, our algorithm compares the prices of a specific day to the previous days and determines if that day is unusually expensive.  

All the constant parameters we use for the algorithm are configured int the CAD_conf.yml file and can be easily modified.  
We tested and fine-tuned them on real traffic, so generally we reccomend not to change them - but in case you receive false positives or miss anomalies, you may lower/increase them.  

#### Algorithm Flow
* The anomaly detector queries the billing data from the last 14 days (by default)
* The anomaly detector reads the queries section of the CAD_conf.yml file and runs the following steps for each query specified:
	* Caluculates the cost of the resources specified in the query for each day in range (*excluding costs of reserved resources*)
	* Calculates the average daily cost and the standard deviation
	* Marks the query as an anomaly only if *all 3 thresholds* where crossed:
		* *relative threshold*: The day checked is at least 1.25 times the average cost of previous days. (by default)
		* *standard deviation threshold*: The day checked is at least 4 standard deviations more expensive than the average cost of previous days. (by default)
		* *absolute threshold*: The day checked is more expensive than $10. (by default)
		
We found out that we get the best results by using all 3 thresholds together, each for it's own reason:  
*Relative threshold* filters out insignificant anomalies.  
*Standard deviation threshold* filters out regular usage of services with normal differing daily usage (high days/low days).
*Absolute threshold* prevents us from getting notified about inexpensive anomalies, which will lead to no action.
	


## Setup & Deployment
To start using the anomaly detector you’ll have to go through just a few simple steps!

* Configure CUR to be written to a bucket with redshift copy command  
	(if you already have the report, make sure the required options are enabled)
	* In the AWS console Go to:  
		My Account --> Reports --> Create New Report
	* Mark the following:
			* Time unit: hour
			* Include: Resource IDs
			* Enable support for Redshift
	* Choose S3 bucket and prefix (save them for later)
* Create Redshift table
	* Use the following SQL command on your Redshift cluster:  
	```sql
  CREATE TABLE IF NOT EXISTS "public"."awsbilling_anomalies" ("anomaly_date" DATE   ENCODE lzo,"service" VARCHAR(512)   ENCODE lzo,"isanomaly" INTEGER   ENCODE lzo,"daily_cost" NUMERIC(10,2)   ENCODE lzo,"mean_cost" NUMERIC(10,2)   ENCODE lzo,"std_cost" NUMERIC(10,2)   ENCODE lzo	,"score" NUMERIC(10,2)   ENCODE lzo);
  ```
* Upload Lambda Code to S3
  * *deployment/CUR_to_Redshift_lambda.zip*
* Edit and then upload configuration file to S3 (parameters detailed in the section below)
  * *deployment/CAD_conf.yml*
* Run CloudFormation (parameters detailed in the section below)
  * *deployment/anomaly_detector.yml*
* (optional) If left the redshift_role parameter in the conf file empty
  * Add the Instance role created by the cloudformation to your Redshift cluster:
    * In the aws console go to:  
      redshift --> clusters --> your cluster --> manage IAM roles
    * Add the anomalyDetectorInstanceRole
    * Edit your CAD_conf.yml file and set the param value to the role's ARN (can be found in the IAM console --> Roles --> anomalyDetectorInstanceRole)
* Set trigger for the Lambda function:  
  * In the AWS console go to:  
    Lambda --> CUR_Write_Trigger --> Triggers --> add trigger
  * Choose S3
    * *Bucket*: choose your CUR bucket
    * *Prefix*: enter your reports prefix
    * *Suffix*: enter `RedshiftCommands.sql`


### CloudFormation
The cloudformation is written in YAML format.
Generally, there is no reason to open or change it, just input the parameter values in the aws console.

#### Parameters:
* **AutoScalingGroupAvailabilityZone**
  * *Usage*: The availability zone in which the anomaly instance would be started, can be one or more.
  * *Example*: us-east-1d
* **ConfigurationFilePath**
  * *Usage*: The configuration file would be downloaded on instance startup and used for the scripts.
  * *Example*: my-bucket/directory/CAD_conf.yml
* **gitBranch**
  * *Usage*: The branch of sundaysky's anomaly detector repo that would be pulled on instance startup.
  * *Default*: master. Unless you want to create and use your on branch, there is no need to change it.
  * *Example*: master, my-branch
* **InstanceImageId**
  * *Usage*: The image used for the anomaly instance, we reccomendend using the lastest AWS linux AMI by AWS.
  * *Example*: ami-a4c7edb2
* **InstanceKeyPair**
  * *Usage*: The key-pair used to log in to the instance
  * *Example*: my-key-pair
* **InstanceSecurityGroup**
  * *Usage*: Security groups provided to the instance and the lambda
		 * required: access from the lambda (the same vpc, security groups), access to the redshift database (we reccomend same vpc as the db)
		 * reccomendend: ssh access to the instance for you
  * *Example*: sg-abcd, vpc-security-group
* **InstanceSubnets**
  * *Usage*: Subnets available for the instance. 
		 * *Required*: at least 1 per availability-zone provided above
  * *Example*: subnet-abcd, subnet-vpc-private
* **InstanceType**
  * *Usage*: the anomaly instance type (defaults and reccomend: t.micro, no need for an expensive instance)
  * *Example*: t2.micro, c4.large
* **LambdaCodeBucket**
  * *Usage*: The bucket where you uploaded the lambda code
  * *Example*: my-bucket
* **LambdaCodeKey**
  * *Usage*: The key for the zip file
  * *Example*: directory/CUR_to_Redshift_lambda.zip

  
### Configuration File
the configuration file is created in YAML format, there is an example CAD_conf.yml file in the 'deployment' directory.  
Please edit the file according to your usage and upload it to s3.

The parameters in the file are divided to 3 sections:
	DB params - Should be changed according to your database.
	Algorithem params - Thresholds for anomalies. Generally, should not be modified at all.
	Queries - We provide some examples, you should add/remove queries to get the most relevant data to your account and use cases. (This part will have it's own section)

##### DB params
* **redshift_user** (*String*)
  * *Usage*: The database user used to run the SQL commands. the user must have SELECT, CREATE and UPDATE (we reccomend GRANT as well).
* **redshift_password** (*String*)
  * *Usage*: password for the database user.
* **redshift_db_name** (*String*)
  * *Usage*: The RedShift database name used for the connection (as shown in aws redshift console)
  * *Example*: dbname
* **redshift_hostname** (*String*)
  * *Usage*: endpoint used to connect to the database (as shown in aws redshift console)
  * *Example*: dbname.abcd.region.redshift.amazonaws.com
* **redshift_role** (*String*)
  * *Usage*: full ARN of the role currently used by the redshift cluster. The role must have read access to the CUR S3 bucket. 
  We reccomend using the arn for the anomalyDetectorInstanceRole created by the cloudformation.  
  *If you do, leave that param empty, run the clouformation, and then follow the step described in the setup section*.
  * *Example*: arn:aws:iam::12345:role/Redshift_role
* **redshift_table_permitted_users** (*String, Optional*)
  * *Usage*: Give users read permission to the billing tables. T string can contain the name of a user or names of a few users seperated by ,
  * *Example*: admin,quicksight,monitoring,jhon
* **s3_aws_region** (*String*)
  * *Usage*: The AWS region of the bucket containig the CURs
  * *Example*: us-east-1

##### Algorithem params
* **threshold_relative** (*float*)
  * *Usage*: explained in Algorithem section above
  * *Default*: 1.25
* **threshold_std** (*int*)
  * *Usage*: explained in Algorithem section above
  * *Default*: 4
* **threshold_absolute** (*int*)
  * *Usage*: explained in Algorithem section above
  * *Default*: 10
* **history_period_days** (*int*)
  * *Usage*: explained in Algorithem section above
  * *Default*: 14 
* **aws_account** (*String or List of Strings, Optional*)
  * *Usage*: In case your CUR contain data for more than 1 aws account, you can specify which accounts do you want to run the algorithm for. Input accountId string or list of account Ids
  * *Default*: All accounts that appear in the CUR
  * *Example*: 123456789012
* **aws_query_regions** (*List of Strings*)
  * *Usage*: All aws region in which you have aws resources. Usage will be explained in the Queries section below.
* **log_folder** (*String*)
  * *Usage*: Folder for CUR_writer and anomaly detector logs
  * *Default*: /sundaysky/logs/anomaly_detector/

#### Queries
The real power of the anomaly detector comes from the possibility to easliy analyze many differnt combinations of data relevant for your specific account and use cases.  
To do so, you would define the queries relevant for you in the queries section of the CAD_conf.yml file.  

The anomaly detector can divide your data in 4 methods:
* *By AWS Service*: such as ec2, s3, lambda, etc..
* *By AWS Operation*: such as RunInstances, LoadBalancing, PutObject, GetObject, etc..
* *By AWS Region*: such as us-east-1, eu-west-2, etc...
* *By Resource Tags*: user given tags. Smart usage of tags will enable you to get exceptional value!


##### Write your own queries
The queries are written in easily readable yaml format. We already added a few example queries to the example CAD_conf.yml file.  
Example queries:
```yaml
queries:
  ec2:
    service: AmazonEC2
    region: all
  ec2_instances:
    service: AmazonEC2
    operation: RunInstances*
    region: us-east-1, us-west-1
```

Lets go over some important things to know:
* *Service/Operation*: You can use the SQL queries in the bottom on your billing table to find the right values for those fields (relevant to you)
* *Region*: Can receive 3 types of values:
	* single region: (example: us-east-1)
	* multiple regions: (example: us-east-1,us-west-1)
	* all regions: all region you use, as defined in 'aws_query_regions' parameter in the conf file.  
	  If you input more than one region, the query would be replicated and run seperately, once for each region and once for all region combined (general),
	you will see all of them in the results table.
* *Tags*: Just use your tag key as key and it's value as value.  

For example, to check my web servers usage, I would make a query to check all instances with tag 'component' equals 'web':
```yaml
queries:
  ec2_web_instances:
    service: AmazonEC2
    operation: RunInstances*
    component: web
```
If I would like to check my general web usage, but also find out if anomalies occur on any specific region:
```yaml
queries:
  ec2_web_instances:
    service: AmazonEC2
    operation: RunInstances*
    component: web
    region: all
```

### Usage
coming soon...

#### Useful SQL queries
**Get relative date results**  
yesterday:
```sql
SELECT * FROM awsbilling_anomalies WHERE anomaly_date=DATE 'yesterday';
```
2 days ago:
```sql
SELECT * FROM awsbilling_anomalies WHERE anomaly_date=DATE 'today'-2;
```

**Get results by date**  
*by date*:
```sql
SELECT * FROM awsbilling_anomalies WHERE anomaly_date=DATE '2017-10-15';
```
*Since date*:
```sql
SELECT * FROM awsbilling_anomalies WHERE anomaly_date>=DATE '2017-10-15';
```

**Get anomalies**
Add to the end of one of the queries above:
```sql
AND isanomaly=1;
```

##### General Data
**Get your billing tables**
```sql
SELECT DISTINCT tablename FROM PG_TABLE_DEF	WHERE tablename ilike 'awsbilling%';
```

**Get AWS Service names**
Using this query would give you the names of all AWS service you pay for. Those are the names you should you in your queries 'service' parameter
```sql
SELECT lineitem_productcode as service FROM awsbilling201710 GROUP BY lineitem_productcode;
```
**Get AWS Operation names**
Using this query would give you the names of all AWS operations you pay for. Those are the names you should you in your queries 'operation' parameter
```sql
SELECT lineitem_operation as operation FROM awsbilling201710 GROUP BY lineitem_operation;
```
