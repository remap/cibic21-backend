import boto3
import hashlib
import json
import sys, traceback, os
import urllib.request, mimetypes
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

def fetchWeatherJson(lat, lon, accuweatherLocationUrl, accuweatherConditionsUrl,
      accuweatherApiKey, requests):
    """
    Use the lat, lon to fetch the Accuweather location key, and use that to
    fetch the weather conditions. Return a JSON string of the entire response.
    You must pass in requests because this requires the Lambda to include the
    layer for it. If there is an error, print the error and return None.
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
    messageJson = json.dumps(message)
    maxPrintLen = 200
    if len(messageJson) <= maxPrintLen:
        print('lambda reply {} {}'.format(code, messageJson))
    else:
        print('lambda reply {} {} ...'.format(code, messageJson[0:maxPrintLen]))

    return {
        'statusCode': code,
        'body': messageJson
    }

def malformedMessageReply():
    return lambdaReply(420, 'Malformed message received')

def processedReply():
    return lambdaReply(200, 'Message processed')

################################################################################
# GEO MATH HELPERS
################################################################################

def splitWaypoints(radius, waypoints):
    """
    Split waypoints into three groups:
    1) 'start' zone: waypoints that fall within given radius of the first waypoint
    2) 'end' zone:  waypoints that fall within given radius of the last waypoint
    3) 'main' zone: all other waypoints.
    Each waypoint has float 'latitude' and 'longitude'. This adds 'originalIdx'
    and 'zone'. Return return (startZone, endZone, mainZone) .
    """
    if len(waypoints):
        startWp = waypoints[0]
        endWp = waypoints[-1]
        startZone = [startWp]
        endZone = []
        mainZone = []
        wpIdx = 0
        for wp in waypoints:
            wp['originalIdx'] = wpIdx
            dStart = getGreatCircleDistance(startWp['latitude'], startWp['longitude'],
                        wp['latitude'], wp['longitude'])
            dEnd = getGreatCircleDistance(endWp['latitude'], endWp['longitude'],
                        wp['latitude'], wp['longitude'])
            if dStart <= radius or dEnd <= radius:
                if dStart <= radius:
                    wp['zone'] = 'start'
                    startZone.append(wp)
                if dEnd <= radius:
                    wp['zone'] = 'end'
                    endZone.append(wp)
            else:
                wp['zone'] = 'main'
                mainZone.append(wp)
            wpIdx += 1
        endZone.append(endWp)
        print('split waypoints: start {}, end {}, main {}'
                .format(len(startZone), len(endZone), len(mainZone)))
        return (startZone, endZone, mainZone)
    return ([],[],[])

def obfuscateWaypoints(waypoints, id, obfuscateSalt):
    """
    Each waypoint has float 'latitude' and 'longitude'.
    Use strings id and obfuscateSalt to derive an offset for the center which is
    always the same for the id (and obfuscateSalt).
    Return (centerLat, centerLon, minRadius) .
    """
    centerLat = 0
    centerLon = 0
    # find "center of mass" of all waypoints
    # TODO: what if center is too close to the waypoint we want to obfuscate
    # (i.e. len(waypoints) == 1)
    for wp in waypoints:
        centerLat += wp['latitude']
        centerLon += wp['longitude']
    centerLat /= float(len(waypoints))
    centerLon /= float(len(waypoints))
    # find min radius to cover all waypoints
    minRadius = 0
    for wp in waypoints:
        d = getGreatCircleDistance(wp['latitude'], wp['longitude'], centerLat, centerLon)
        if minRadius < d:
            minRadius = d

    # Compute an offset for center lat and lon in the range -50 to 50 (meters).
    sha256 = hashlib.sha256()
    sha256.update(str.encode(id))
    sha256.update(str.encode(obfuscateSalt))
    digest = sha256.digest()
    # Use a byte of the digest as a pseudo-random value from 0 to 255.
    randMetersY = float(digest[0]) / 255.0 * 100.0 - 50.0
    randMetersX = float(digest[1]) / 255.0 * 100.0 - 50.0
    # Convert meters at the Earth radius to (approximate) degrees.
    R = 6378.137 * 1000.0 # Earth radius in meters.
    offsetLat = math.degrees(math.atan2(randMetersY, R))
    offsetLon = math.degrees(math.atan2(randMetersX, R))

    return (centerLat + offsetLat, centerLon + offsetLon, minRadius)

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
    # dA = math.acos(math.sin(lat1)*math.sin(lat2) + math.cos(lat1)*math.cos(lat2)*math.cos(dLon))
    dA = math.acos(max(-1.0,min(1.0,math.sin(lat1)*math.sin(lat2) + math.cos(lat1)*math.cos(lat2)*math.cos(dLon))))
    return dA * R * 1000 # convert to meters
