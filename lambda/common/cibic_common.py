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
        # By default, table names are for the prod stage. For the dev stage, append "-dev".
        EndpointRequests = 'cibic21-dynamodb-api-endpoint-requests'
        JournalingRequests = 'cibic21-dynamodb-api-journaling-requests'
        ModeratedJournalingRequests = 'cibic21-dynamodb-moderated-journaling-requests'
        RideData = 'cibic21-dynamodb-ride-data'
        FilteredJournalingData = 'cibic21-dynamodb-exhibit-filtered-journaling-data'
        RawSurveyResponses = 'cibic21-dynamodb-raw-survey-responses'

    class Postgres():
        # By default, table names are for the prod stage. For the dev stage, append "_dev".
        Rides = 'cibic21_rides'
        WaypointsRaw = 'cibic21_waypoints_raw'
        RideFlowWaypoints = 'cibic21_ride_flow_waypoints'
        WaypointsSnapped = 'cibic21_waypoints_snapped'
        UserEnrollments = 'cibic21_user_enrollments'

    class S3Bucket():
        JournalingImages = 'cibic21-s3-journaling-images'

    Organization = 'CiBiC'
    LosAngelesRegion = 'Los Angeles'
    BuenosAiresRegion = 'Buenos Aires'

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

def fetchWeatherJson(lat, lon, accuweatherLocationUrl, accuweatherConditionsUrl, accuweatherApiKey):
    """
    Use the lat, lon to fetch the Accuweather location key, and use that to
    fetch the weather conditions. Return a JSON string of the entire response.
    If there is an error, print the error and return None.
    """
    # Fetch the location key.
    response = requests.get(
        '{}?apikey={}&q={}%2C{}'.format(accuweatherLocationUrl, accuweatherApiKey, lat, lon))
    if response.status_code/100 == 2:
        locationKey = response.json()['Key']
    else:
        err = 'Accuweather location API request failed with code {}'.format(response.status_code)
        print(err)
        return None

    # Fetch the weather conditions.
    response = requests.get(
        '{}/{}?apikey={}&language=en-us'.format(accuweatherConditionsUrl, locationKey, accuweatherApiKey))
    if response.status_code/100 == 2:
        if len(response.json()) == 1:
            return json.dumps(response.json()[0])
        else:
            err = 'Expected 1 Accuweather result. Got {}: {}'.format(len(response.json()), response.json())
            print(err)
            return None
    else:
        err = 'Accuweather conditions API request failed with code {}'.format(response.status_code)
        print(err)
        return None

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
    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    R = 6378.137 # earth radius in km
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    lon1 = math.radians(lon1)
    lon2 = math.radians(lon2)
    dLon = abs(lon1-lon2)
    dA = math.acos(math.sin(lat1)*math.sin(lat2) + math.cos(lat1)*math.cos(lat2)*math.cos(dLon))
    return dA * R * 1000 # convert to meters
