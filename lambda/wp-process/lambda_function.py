from common.cibic_common import *
import os
import psycopg2
from psycopg2 import extras # for fast batch insert, see https://www.psycopg.org/docs/extras.html#fast-exec

obfuscateRadius = float(os.environ['ENV_VAR_OBFUSCATE_RADIUS']) if 'ENV_VAR_OBFUSCATE_RADIUS' in os.environ else 2000
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_PPOSTGRES_SERVER']

# process waypoints data
# expected payload:
# {
#   'rid': "API-endpoint-request-id",
#   'data': { 'id' : "rideId", 'waypoints' : <waypoints-data> }
# }
def lambda_handler(event, context):
    try:
        if 'rid' in event and 'data' in event:
            payload = event['data']
            if 'id' in payload and 'waypoints' in payload:
                rideId = payload['id']
                waypoints = validateWaypoints(payload['waypoints'])
                print ('API request {} process waypoints for ride {} ({} waypoints)'
                    .format(event['rid'], rideId, len(waypoints)))

                # calculate route derived data
                derivedData = processWaypoints(waypoints)

                # split waypoints into three zones
                startZone, endZone, routeWaypoints = splitWaypoints(obfuscateRadius, waypoints)
                # generate start / end geometry
                # startArea = generateAreaGeometry(startZone)
                # endArea = generateAreaGeometry(endZone)

                conn = psycopg2.connect(host=pgServer, database=pgDbName,
                    user=pgUsername, password=pgPassword)
                cur = conn.cursor()
                cur.execute('SELECT version()')
                db_version = cur.fetchone()
                print('postgres version ' + str(db_version))

                # insert new ride
                sqlInsertRide = 'INSERT INTO cibic21_rides("rideId") VALUES(%s)'
                cur.execute(sqlInsertRide, (rideId,))

                # insert raw waypoints
                insertRawWaypoints(cur, rideId, routeWaypoints)
                conn.commit()

                print(cur.statusmessage)
                # obfuscate route around start and end

                cur.close()

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
    stats = getRouteStats(waypoints)

    # calculate statistics per road type (for example)
    stats['roadTypes'] = {}
    roadTypes = set(map(lambda x: x['road_type'], waypoints))
    routeSegments=[[wp for wp in waypoints if wp['road_type'] == rt] for rt in roadTypes]
    for idx,rt in enumerate(roadTypes):
        stats['roadTypes'][rt] = getRouteStats(routeSegments[idx])

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

# removes waypoints that fall within given radius from start and end waypoint
# returns three arrays:
#    1) waypoints that fall into start circle
#    2) waypoints that fall into end circle
#    3) all other waypoints
def splitWaypoints(radius, waypoints):
    if len(waypoints):
        startWp = waypoints[0]
        endWp = waypoints[-1]
        startCircleWps = [startWp]
        endCircleWps = [endWp]
        otherWps = []
        wpIdx = 0
        for wp in waypoints:
            wp['originalIdx'] = wpIdx
            dStart = getGreatCircleDistance(startWp['latitude'], startWp['longitude'],
                        wp['latitude'], wp['longitude'])
            dEnd = getGreatCircleDistance(endWp['latitude'], endWp['longitude'],
                        wp['latitude'], wp['longitude'])
            if dStart <= radius or dEnd <= radius:
                if dStart <= radius:
                    startCircleWps.append(wp)
                if dEnd <= radius:
                    endCircleWps.append(wp)
            else:
                otherWps.append(wp)
            wpIdx += 1
        print('split waypoints: start group {}, end group {}, route {}'
                .format(len(startCircleWps), len(endCircleWps), len(otherWps)))
        return (startCircleWps, endCircleWps, otherWps)

def generateAreaGeometry(waypoints):
    pass

def makeSqlPoint(lat, lon):
    return str(lon) + ', ' + str(lat)

def insertRawWaypoints(cur, rideId, waypoints):
    sql = """
            INSERT INTO cibic21_waypoints_raw
            VALUES %s
          """
    values = list((rideId, makeSqlPoint(wp['latitude'], wp['longitude']),
                    wp['timestamp'], wp['road_type'], wp['speed'], wp['distance'],
                    wp['speed_limit'], wp['originalIdx']) for wp in waypoints)
    # print(values)
    extras.execute_values(cur, sql, values)
    print('sql query execute result: ' + str(cur.statusmessage))
