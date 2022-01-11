import boto3
import copy
import json
from decimal import Decimal
import sys, traceback, os
import uuid
from datetime import datetime
import urllib.request, mimetypes
import statistics
import time

################################################################################
# All AWS resource names
################################################################################
class CibicResources():
    class DynamoDB():
        EndpointRequests = 'cibic21-dynamodb-api-endpoint-requests'

    # class S3Bucket():
        # SurveyMedia = # TBD

    # class Sns():
        # EndpointRequestProcessed = # TBD

################################################################################
# GENERAL HELPERS
################################################################################
def reportError():
    type, err, tb = sys.exc_info()
    print('caught exception:', err)
    traceback.print_exc(file=sys.stdout)
    return err

def guessMimeTypeFromExt(fileName):
    # try to guwss from file extension first
    type, _ = mimetypes.guess_type(urllib.request.pathname2url(fileName))
    if type:
        return type
    return None

def guessMimeTypeFromFile(fileName):
    ## try reading the header
    res = os.popen('file --mime-type '+fileName).read()
    type = res.split(':')[-1].strip()
    return type

################################################################################
# LAMBDA HELPERS
################################################################################
def lambdaReply(code, message):
    print('lambda reply {}: {}'.format(code, message))
    return {
        'statusCode': code,
        'body': json.dumps(message)
    }

def malformedMessageReply():
    return lambdaReply(420, 'Malformed message received')

def processedReply():
    return lambdaReply(200, 'Message processed')
