from common.cibic_common import *
import os
import psycopg2
from psycopg2 import extras # for fast batch insert, see https://www.psycopg.org/docs/extras.html#fast-exec
import urllib.parse

# Python 3.8 lambda environment does not have requests https://stackoverflow.com/questions/58952947/import-requests-on-aws-lambda-for-python-3-8
# for a fix, see https://dev.to/razcodes/how-to-create-a-lambda-layer-in-aws-106m
import requests

pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
roadsApiKey = os.environ['ENV_VAR_GOOGLE_API_KEY']
rideReadyTopic = os.environ['ENV_SNS_RIDE_READY']
roadsApiUrl = 'https://roads.googleapis.com/v1/snapToRoads?key={}&interpolate={}&path={}'

snsClient = boto3.client('sns')

# lambda is triggered by SNS notification
# SNS message expected payload:
# { "id": "<ride-id>", "requestId": "<request-id>", "rideData": {} }
def lambda_handler(event, context):
    try:
        # print (event)
        for rec in event['Records']:
            payload = json.loads(rec['Sns']['Message'])
            if 'id' in payload and 'requestId' in payload:
                rideId = payload['id']
                requestId = payload['requestId']
                print ('route snapping for ride id {}, requestId {}'.format(rideId, requestId))

                conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                        user=pgUsername, password=pgPassword)
                cur = conn.cursor()

                # retrieve waypoints
                waypoints = selectWaypoints(cur, rideId)
                snappedWpts = []

                # roads API limits requests to up to 100 points
                batches = [waypoints[i:i+100] for i in range(0, len(waypoints), 100)]
                for b in batches:
                    print('snapping batch of {}'.format(len(b)))
                    url = makeSnappingRequest(b)
                    response = requests.request("GET", url, headers={}, data={})
                    if response.status_code/100 == 2:
                        processedWpts = processSnappingResponse(b, json.loads(response.text))
                        print('received {} processed snapped waypoints'.format(len(processedWpts)))
                        # print(processedWpts)
                        snappedWpts.extend(processedWpts)
                    else:
                        print('Roads API request failed with code {}'.format(response.status_code))

                # store snapped waypoints in DB
                insertSnappedWaypoints(cur, rideId, requestId, snappedWpts)

                conn.commit()
                cur.close()

                # notify waypoints added
                response = snsClient.publish(TopicArn=rideReadyTopic,
                                            Message=json.dumps({'id':rideId, 'requestId':requestId, 'rideData':payload['rideData']}),
                                            Subject='new ride ready',
                                            )['MessageId']
                print('sent ride ready notification: {}'.format(response))
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

def selectWaypoints(cur, rideId):
    sql = """
          SELECT ST_Y(coordinate::geometry) as latitude,
                 ST_X(coordinate::geometry) as longitude,
                 timestamp, "roadType", speed, distance, "speedLimit", idx
          FROM {}
          WHERE "rideId"=%s AND zone=%s
          """.format(CibicResources.Postgres.WaypointsRaw)
    try:
        cur.execute(sql, (rideId, "main"))
        waypoints = []
        for wp in cur.fetchall():
            waypoints.append({
                'latitude': wp[0],
                'longitude': wp[1],
                'timestamp': wp[2].astimezone().strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
                'roadType': wp[3],
                'speed': wp[4],
                'distance': wp[5],
                'speedLimit': wp[6],
                'idx': wp[7]
            })
        # print(waypoints)
        print('{} waypoints fetched'.format(len(waypoints)))
        return waypoints
    except (Exception, psycopg2.Error) as error:
        print("error fetching data from PostgreSQL table", error)
    return []

def makeSnappingRequest(waypoints):
    pathParam = ''
    for wp in waypoints:
      if len(pathParam): pathParam = pathParam + '|'
      pathParam += '{},{}'.format(wp['latitude'], wp['longitude'])
    return roadsApiUrl.format(roadsApiKey, 'true', urllib.parse.quote(pathParam))

def processSnappingResponse(waypoints, response):
    snappedWpts = []
    for snappedWp in response.get('snappedPoints', []):
        rawIdx = -1
        isInterpolated = not 'originalIndex' in snappedWp
        if not isInterpolated:
            origIdx = snappedWp['originalIndex']
            rawIdx = origIdx + waypoints[origIdx]['idx']
        snappedWpts.append({
            'latitude': snappedWp['location']['latitude'],
            'longitude': snappedWp['location']['longitude'],
            'googlePlaceId': snappedWp['placeId'],
            'isInterpolated': isInterpolated,
            'rawIdx': rawIdx
        })
    return snappedWpts

def makeSqlPoint(lat, lon):
    return str(lon) + ', ' + str(lat)

def insertSnappedWaypoints(cur, rideId, requestId, waypoints):
    sql = """
            INSERT INTO {}
            VALUES %s
          """.format(CibicResources.Postgres.WaypointsSnapped)
    values = list((rideId, makeSqlPoint(wp['latitude'], wp['longitude']),
                    wp['rawIdx'], wp['isInterpolated'],
                    wp['googlePlaceId'], idx, requestId) for idx, wp in enumerate(waypoints))
    extras.execute_values(cur, sql, values)
    print('sql query execute result: ' + str(cur.statusmessage))
