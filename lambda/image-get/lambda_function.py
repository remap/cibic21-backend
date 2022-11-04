# This Lambda is called by an HTTP endpoint with a URL like:
# https://<API>.execute-api.us-west-1.amazonaws.com/prod/get?password=<password>&path=<path>.
# Get the object from S3 and return the result.

import os
import mimetypes
import boto3
import base64
import urllib
from common.cibic_common import *

s3 = boto3.client('s3')

getPassword = os.environ['ENV_VAR_GET_PASSWORD']

def lambda_handler(event, context):
    mimetypes.init()
    requestReply = {}

    try:
        print ('event data ' + str(event))

        stage = event['requestContext'].get('stage')

        if event['requestContext'].get('http', {}).get('method') == 'GET':
            if event.get('queryStringParameters', {}).get('password') == getPassword:
                path = urllib.parse.unquote(event.get('queryStringParameters', {}).get('path', ''))
                print('Getting path "' + path + '"')

                response = s3.get_object(
                  Bucket=CibicResources.S3Bucket.JournalingImages,
                  Key=path,
                )
                data = response['Body'].read()

                # Give the response to enable CORS.
                requestReply = {
                    'statusCode': 200,
                    'headers': { 'Content-Type': response['ContentType'] },
                    'body': base64.b64encode(data),
                    'isBase64Encoded': True
                }
            else:
                requestReply = lambdaReply(420, "Wrong password")
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    return requestReply
