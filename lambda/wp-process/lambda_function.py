from common.cibic_common import *
import os
import psycopg2
from psycopg2 import extras # for fast batch insert, see https://www.psycopg.org/docs/extras.html#fast-exec

snsClient = boto3.client('sns')

obfuscateRadius = float(os.environ['ENV_VAR_OBFUSCATE_RADIUS']) if 'ENV_VAR_OBFUSCATE_RADIUS' in os.environ else 100
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
derivedDataReadyTopic = os.environ['ENV_SNS_DERIVED_DATA_READY']
waypointsReadyTopic = os.environ['ENV_SNS_WAYPOINTS_READY']

# process waypoints data
# expected payload:
# {
#   'rid': "API-endpoint-request-id",
#   'data': { 'id' : "rideId", 'waypoints' : <waypoints-data> }
# }
def lambda_handler(event, context):
    try:
        if 'rid' in event and 'data' in event:
            requestId = event['rid']
            payload = event['data']
            if 'id' in payload and 'waypoints' in payload:
                rideId = payload['id']
                waypoints = validateWaypoints(payload['waypoints'])
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

                # insert data into postgres
                conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                        user=pgUsername, password=pgPassword)
                cur = conn.cursor()

                # insert new ride
                insertRide(cur, rideId, requestId, startZone, endZone)
                # insert raw waypoints
                insertRawWaypoints(cur, rideId, requestId, waypoints)

                conn.commit()
                cur.close()

                # notify waypoints added
                response = snsClient.publish(TopicArn=waypointsReadyTopic,
                                            Message=json.dumps({'id':rideId, 'requestId':requestId}),
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
        print('waypoints validataion: found {} waypoints with same timestamp, {} valid waypoints'
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

def insertRide(cur, rideId, requestId, startZone, endZone):
    # generate start / end geometry
    cLat1, cLon1, rad1 = obfuscateWaypoints(startZone)
    cLat2, cLon2, rad2 = obfuscateWaypoints(endZone)
    sqlInsertRide = """
                    INSERT INTO {}("rideId", "requestId", "startTime", "endTime", "startZone", "endZone")
                    VALUES (%s, %s, %s, %s,
                            ST_Buffer(ST_GeomFromText('{}',4326)::geography,
                                        {},'quad_segs=16')::geometry,
                            ST_Buffer(ST_GeomFromText('{}',4326)::geography,
                                        {},'quad_segs=16')::geometry
                    )
                    """.format(CibicResources.Postgres.Rides,
                                wktPoint(cLat1, cLon1), rad1,
                                wktPoint(cLat2, cLon2), rad2)
    cur.execute(sqlInsertRide, (rideId, requestId, startZone[0]['timestamp'], endZone[-1]['timestamp']))

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
            INSERT INTO {}
            VALUES %s
          """.format(CibicResources.Postgres.WaypointsRaw)
    values = list((rideId, makeSqlPoint(wp['latitude'], wp['longitude']),
                    wp['timestamp'], wp['road_type'], wp['speed'], wp['distance'],
                    wp['speed_limit'], wp['originalIdx'], wp['zone'], requestId) for wp in waypoints)
    extras.execute_values(cur, sql, values)
    print('sql query execute result: ' + str(cur.statusmessage))

def makeSqlPoint(lat, lon):
    return str(lon) + ', ' + str(lat)
