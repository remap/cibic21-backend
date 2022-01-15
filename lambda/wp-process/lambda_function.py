from common.cibic_common import *
import os
import psycopg2

obfuscateRadius = os.environ['ENV_VAR_OBFUSCATE_RADIUS'] if 'ENV_VAR_OBFUSCATE_RADIUS' in os.environ else 2000
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
                waypoints = payload['waypoints']
                print ('API request {} process waypoints for ride {} ({} waypoints)'
                    .format(event['rid'], rideId, len(waypoints)))

                totalDist = 0
                avgSpeed = 0
                prevWp = None
                for wp in waypoints:
                    if prevWp:
                        # NOTE: can also use 'distance' from waypoint data, it is within ~1m accuracy
                        totalDist += getGreatCircleDistance(prevWp['latitude'], prevWp['longitude'],
                            wp['latitude'], wp['longitude'])
                    avgSpeed += wp['speed']
                    prevWp = wp
                avgSpeed /= len(waypoints)
                print('total distance {} avg speed {}'.format(totalDist, avgSpeed))

                conn = psycopg2.connect(host=pgServer, database=pgDbName,
                    user=pgUsername, password=pgPassword)
                cur = conn.cursor()
                cur.execute('SELECT version()')
                db_version = cur.fetchone()
                print('postgres version ' + str(db_version))
                cur.close()

                # obfuscate route around start and end
                # startZone, endZone, routeWaypoints = splitWaypoints(obfuscateRadius, waypoints)
                # generate start / end geometry
                # startArea = generateAreaGeometry(startZone)
                # endArea = generateAreaGeometry(endZone)

                # insert raw waypoints
                # insertRawWaypoints(rideId, routeWaypoints)

            else:
                return malformedMessageReply()
        else:
            return malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

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
        for wp in waypoints:
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
        return (startCircleWps, endCircleWps, otherWps)

def generateAreaGeometry(waypoints):
    pass

def insertRawWaypoints(rideId, waypoints):
    pass
