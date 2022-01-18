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
import math

################################################################################
# All AWS resource names
################################################################################
class CibicResources():
    class DynamoDB():
        EndpointRequests = 'cibic21-dynamodb-api-endpoint-requests'
        JournalingRequests = 'cibic21-dynamodb-api-journaling-requests'

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

def unmarshallAwsDataItem(awsDict):
    boto3.resource('dynamodb')
    deserializer = boto3.dynamodb.types.TypeDeserializer()
    pyDict = {k: deserializer.deserialize(v) for k,v in awsDict.items()}
    return pyDict

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

################################################################################
# GEO MATH HELPERS
################################################################################
# https://en.wikipedia.org/wiki/Haversine_formula
def getGreatCircleDistance(lat1, lon1, lat2, lon2):
    R = 6378.137 # earth radius in km
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    lon1 = math.radians(lon1)
    lon2 = math.radians(lon2)
    dLon = abs(lon1-lon2)
    dA = math.acos(math.sin(lat1)*math.sin(lat2) + math.cos(lat1)*math.cos(lat2)*math.cos(dLon))
    return dA * R * 1000 # convert to meters
