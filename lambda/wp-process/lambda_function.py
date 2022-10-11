# Process the waypoints from the ride data: Split into start, end and main zones
# and store in WaypointsRaw with these zone tags. (Send the derivedDataReady SNS.)
# From the ride data, also extract the userId, flow, pod, etc. and store in the
# Rides table. If the user role is 'steward', fetch and include the weather data.
# Also store the flow waypoints in RideFlowWaypoints. Send the waypointsReady SNS.

from common.cibic_common import *
import os
import gzip
import base64
import psycopg2
from psycopg2 import extras # for fast batch insert, see https://www.psycopg.org/docs/extras.html#fast-exec

# Python 3.8 lambda environment does not have requests https://stackoverflow.com/questions/58952947/import-requests-on-aws-lambda-for-python-3-8
# for a fix using Lambda Layers, see https://dev.to/razcodes/how-to-create-a-lambda-layer-in-aws-106m
import requests
from requests.auth import HTTPBasicAuth

snsClient = boto3.client('sns')

obfuscateRadius = float(os.environ['ENV_VAR_OBFUSCATE_RADIUS']) if 'ENV_VAR_OBFUSCATE_RADIUS' in os.environ else 100
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
derivedDataReadyTopic = os.environ['ENV_SNS_DERIVED_DATA_READY']
waypointsReadyTopic = os.environ['ENV_SNS_WAYPOINTS_READY']
accuweatherApiKey = os.environ['ENV_VAR_ACCUWEATHER_API_KEY']
accuweatherLocationUrl = os.environ['ENV_VAR_ACCUWEATHER_LOCATION_URL']
accuweatherConditionsUrl = os.environ['ENV_VAR_ACCUWEATHER_CONDITIONS_URL']

# process waypoints data
# expected payload:
# {
#   'rid': "API-endpoint-request-id",
#   'data': { 'rideData' : {'id': "rideId"}, 'flowData' : <flow-waypoints>, 'waypoints_gz_b64' : <waypoints-data> }
# }
def lambda_handler(event, context):
    try:
        if 'rid' in event and 'data' in event:
            requestId = event['rid']
            payload = event['data']
            if 'rideData' in payload and 'id' in payload['rideData'] and 'waypoints_gz_b64' in payload:
                rideData = payload['rideData']
                flowData = payload['flowData']
                rideId = rideData['id']
                gunzipped_waypoints = json.loads(gzip.decompress(base64.b64decode(payload['waypoints_gz_b64'])))
                waypoints = validateWaypoints(gunzipped_waypoints)
                print ('API request {} process waypoints for ride {} ({} waypoints)'
                    .format(requestId, rideId, len(waypoints)))

                # calculate route derived data
                derivedData = processWaypoints(waypoints)
                # notify new derived data available
                response = snsClient.publish(TopicArn=derivedDataReadyTopic,
                                            Message=json.dumps({'id':rideId, 'derivedData': derivedData }),
                                            Subject='derived data ready',
                                            )['MessageId']
                print('sent derived data ready notification: {}'.format(response))

                # split waypoints into three zones
                startZone, endZone, mainZone = splitWaypoints(obfuscateRadius, waypoints)

                # Add the start and end time to rideData based on start/end zones.
                rideData['startTime'] = startZone[0]['timestamp']
                rideData['endTime'] = endZone[-1]['timestamp']
                # Change ISO time Z to make Python happy.
                if rideData['startTime'].endswith('Z'):
                    rideData['startTime'] = rideData['startTime'][:-1] + '+00:00'
                if rideData['endTime'].endswith('Z'):
                    rideData['endTime'] = rideData['endTime'][:-1] + '+00:00'

                # insert data into postgres
                conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                        user=pgUsername, password=pgPassword)
                cur = conn.cursor()

                # insert new ride
                userId = rideData.get('userId')
                role = rideData.get('role')
                flow = rideData.get('flow')
                commute = rideData.get('commute')
                flowName = None
                flowIsToWork = None
                flowJoinPointsJson = None
                flowLeavePointsJson = None
                pod = None
                podName = None
                podMemberJson = None

                # The rides coming into this endpoint are for Los Angeles.
                region = CibicResources.LosAngelesRegion
                organization = CibicResources.Organization

                if flowData != None:
                    flowName = flowData.get('name')
                    flowIsToWork = flowData.get('isToWork')
                    # Store the join and leave points as JSON as-is.
                    if 'joinPoints' in flowData:
                        flowJoinPointsJson = json.dumps(flowData['joinPoints'])
                    if 'leavePoints' in flowData:
                        flowLeavePointsJson = json.dumps(flowData['leavePoints'])

                    (pod, podName, podMember) = getPodForUser(flowData, userId)
                    if podMember != None:
                        # Store the pod member as JSON as-is.
                        podMemberJson = json.dumps(podMember)

                weatherJson = None
                if role == 'rider' or role == 'steward':
                    # For a steward include the weather (at the start waypoint).
                    weatherJson = fetchWeatherJson(startZone[0]['latitude'], startZone[0]['longitude'],
                      accuweatherLocationUrl, accuweatherConditionsUrl, accuweatherApiKey)

                # TODO: Actually infer the pod.
                inferredPod = pod
                inferredPodName = podName

                insertRide(cur, rideId, requestId, userId, role, flow, flowName, flowIsToWork, commute,
                           flowJoinPointsJson, flowLeavePointsJson, pod, podName, podMemberJson,
                           inferredPod, inferredPodName, weatherJson, region, organization, startZone, endZone)
                # insert raw waypoints
                insertRawWaypoints(cur, rideId, requestId, waypoints)
                # Insert the flow waypoints which may change over time for the same flow ID.
                if flow != None and 'route' in flowData:
                    # Locally assign the waypoint indexes.
                    idx = 0
                    for wp in flowData['route']:
                        wp['idx'] = idx
                        idx += 1

                    insertFlowWaypoints(cur, rideId, requestId, flow, flowData['route'])

                conn.commit()
                cur.close()

                # notify waypoints added
                response = snsClient.publish(TopicArn=waypointsReadyTopic,
                                            Message=json.dumps({'id':rideId, 'requestId':requestId, 'rideData':rideData}),
                                            Subject='waypoints ready',
                                            )['MessageId']
                print('sent waypoints ready notification: {}'.format(response))
            else:
                return malformedMessageReply()
        else:
            return malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

# NOTE: sample data  contains waypoints with identical timestamps
# TODO: ask @Florian if that's possible for real data and cleanup if needed
# this function leaves last (as encountered in waypoints array) waypoint out of
# multiple with same timestamp
def validateWaypoints(waypoints):
    tsWaypointDict = {}
    nDuplicate = 0
    for wp in waypoints:
        if wp['timestamp'] in tsWaypointDict:
            nDuplicate += 1
        tsWaypointDict[wp['timestamp']] = wp
    if nDuplicate > 0:
        validated = [tsWaypointDict[k] for k in sorted(tsWaypointDict.keys())]
        print('waypoints validation: found {} waypoints with same timestamp, {} valid waypoints'
                .format(nDuplicate, len(validated)))
        return validated
    return waypoints

def processWaypoints(waypoints):
    # calculate whole route statistics
    stats = [{ 'total': getRouteStats(waypoints) }]

    # calculate statistics per road type (for example)
    # stats['roadTypes'] = {}
    roadTypes = set(map(lambda x: x['road_type'], waypoints))
    routeSegments=[[wp for wp in waypoints if wp['road_type'] == rt] for rt in roadTypes]
    for idx,rt in enumerate(roadTypes):
        stats.append({ rt :  getRouteStats(routeSegments[idx]) })
        # stats['roadTypes'][rt] = getRouteStats(routeSegments[idx])

    print('calculated route statistics {}'.format(stats))
    return stats

# returns simple statistics:
# - total distance travelled
# - average speed
def getRouteStats(waypoints):
    totalDist = 0
    avgSpeed = 0
    prevWp = None
    for wp in waypoints:
        if prevWp:
            # NOTE: can also use 'distance' from waypoint data, it is within ~1m accuracy
            totalDist += getGreatCircleDistance(prevWp['latitude'], prevWp['longitude'],
                                                wp['latitude'], wp['longitude'])
        prevWp = wp
        avgSpeed += wp['speed']
    # calculate avg speed by finding average speed of all segments
    # one can also use total distance and start/end timestamp
    avgSpeed /= len(waypoints)
    return { 'totalDist' : totalDist, 'avgSpeed' : avgSpeed }

# splits waypoints into three groups:
#    1) start zone: waypoints that fall within given radius of the first waypoint
#    2) end zone:  waypoints that fall within given radius of the last waypoint
#    3) main zone: all other waypoints
def splitWaypoints(radius, waypoints):
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

def insertRide(cur, rideId, requestId, userId, role, flow, flowName, flowIsToWork, commute,
               flowJoinPointsJson, flowLeavePointsJson, pod, podName, podMemberJson,
               inferredPod, inferredPodName, weatherJson, region, organization, startZone, endZone):
    # generate start / end geometry
    cLat1, cLon1, rad1 = obfuscateWaypoints(startZone)
    cLat2, cLon2, rad2 = obfuscateWaypoints(endZone)
    sqlInsertRide = """
                    INSERT INTO {}("rideId", "requestId", "startTime", "endTime", "userId", "role", "flow", "flowName", "flowIsToWork", "commute",
                                   "flowJoinPointsJson", "flowLeavePointsJson", "pod", "podName", "podMemberJson",
                                   "inferredPod", "inferredPodName", "weatherJson", region, organization, "startZone", "endZone")
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            ST_Buffer(ST_GeomFromText('{}',4326)::geography,
                                        {},'quad_segs=16')::geometry,
                            ST_Buffer(ST_GeomFromText('{}',4326)::geography,
                                        {},'quad_segs=1')::geometry
                    )
                    """.format(CibicResources.Postgres.Rides,
                                wktPoint(cLat1, cLon1), rad1,
                                wktPoint(cLat2, cLon2), rad2)
    cur.execute(sqlInsertRide, (rideId, requestId, startZone[0]['timestamp'], endZone[-1]['timestamp'], userId, role, flow, flowName, flowIsToWork, commute,
                                flowJoinPointsJson, flowLeavePointsJson, pod, podName, podMemberJson, inferredPod, inferredPodName, weatherJson, region, organization))

def obfuscateWaypoints(waypoints):
    centerLat = 0
    centerLon = 0
    # find "center of mass" of all waypoints
    # TODO: what if center is too close to the waypoint we want to obfuscate
    # (i.e. len(waypoints) == 1)
    for wp in waypoints:
        centerLat += wp["latitude"]
        centerLon += wp["longitude"]
    centerLat /= float(len(waypoints))
    centerLon /= float(len(waypoints))
    # find min radius to cover all waypoints
    minRadius = 0
    for wp in waypoints:
        d = getGreatCircleDistance(wp["latitude"], wp["longitude"], centerLat, centerLon)
        if minRadius < d:
            minRadius = d
    print('zone center at ({},{}) with radius {}'
            .format(centerLat, centerLon, minRadius))
    return (centerLat, centerLon, minRadius)

def wktPoint(lat, lon):
    return 'POINT({} {})'.format(lon, lat)

def insertRawWaypoints(cur, rideId, requestId, waypoints):
    sql = """
            INSERT INTO {} ("rideId", coordinate, timestamp, "roadType", speed, distance, "speedLimit", idx, zone, "requestId", "pointJson")
            VALUES %s
          """.format(CibicResources.Postgres.WaypointsRaw)
    values = list((rideId, makeSqlPoint(wp['latitude'], wp['longitude']),
                    wp['timestamp'], wp['road_type'], wp['speed'], wp['distance'],
                    wp['speed_limit'], wp['originalIdx'], wp['zone'], requestId,
                    # Cache the JSON of the point with the timestamp.
                    '[' + str(wp['longitude']) + ', ' + str(wp['latitude']) + ', 0, "' + wp['timestamp'] + '"]')
                  for wp in waypoints)
    extras.execute_values(cur, sql, values)
    print('sql insert raw waypoints execute result: ' + str(cur.statusmessage))

def insertFlowWaypoints(cur, rideId, requestId, flow, waypoints):
    try:
        sql = """
                INSERT INTO {} ("rideId", flow, coordinate, idx, "requestId")
                VALUES %s
              """.format(CibicResources.Postgres.RideFlowWaypoints)
        values = list((rideId, flow, makeSqlPoint(wp['lat'], wp['long']),
                       wp['idx'], requestId) for wp in waypoints)
        extras.execute_values(cur, sql, values)
        print('sql insert flow waypoints execute result: ' + str(cur.statusmessage))
    except:
        print('caught exception in insertFlowWaypoints:', sys.exc_info()[0])

def makeSqlPoint(lat, lon):
    return str(lon) + ', ' + str(lat)

def getPodForUser(flow, userId):
    """
    Search the flow for the first pod which mentions the userId and return
    (podId, podName, podMember) where podMember is the entire member object.
    If not found, return (None, None, None).
    This is similar to the same function in get-user-enrollments.
    """
    if 'pods' in flow:
        for pod in flow['pods']:
            if 'members' in pod:
                for member in pod['members']:
                    if member.get('username') == userId:
                        return (pod.get('id'), pod.get('name'), member)

    # Not found
    return (None, None, None)
