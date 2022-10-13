# This Lambda is for fetching ride info from the RideWithGPS API.

import psycopg2
from psycopg2 import extras # for fast batch insert, see https://www.psycopg.org/docs/extras.html#fast-exec
from common.cibic_common import *
from datetime import datetime

# Python 3.8 lambda environment does not have requests https://stackoverflow.com/questions/58952947/import-requests-on-aws-lambda-for-python-3-8
# for a fix using Lambda Layers, see https://dev.to/razcodes/how-to-create-a-lambda-layer-in-aws-106m
import requests

obfuscateRadius = float(os.environ['ENV_VAR_OBFUSCATE_RADIUS']) if 'ENV_VAR_OBFUSCATE_RADIUS' in os.environ else 100
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
clubId = os.environ['ENV_VAR_RWGPS_CLUB_ID']
apiKey = os.environ['ENV_VAR_RWGPS_API_KEY']
authToken = os.environ['ENV_VAR_RWGPS_AUTH_TOKEN']
accuweatherApiKey = os.environ['ENV_VAR_ACCUWEATHER_API_KEY']
accuweatherLocationUrl = os.environ['ENV_VAR_ACCUWEATHER_LOCATION_URL']
accuweatherConditionsUrl = os.environ['ENV_VAR_ACCUWEATHER_CONDITIONS_URL']

def lambda_handler(event, context):
    requestReply = {}
    err = ''

    try:
        # Fetch the routes for the club.
        routes = fetchRoutes()
        for id, route in routes.items():
            print("Route " + str(id) + ' "' + str(route.get('name')) + '"')

        conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                user=pgUsername, password=pgPassword)
        cur = conn.cursor()

        # The users coming from ENV_VAR_RWGPS_CLUB_ID are for Buenos Aires.
        region = CibicResources.BuenosAiresRegion
        organization = CibicResources.Organization

        users = queryActiveUsers(cur, region, organization)
        existingRides = queryRideIds(cur, region)

        for userId, user in users.items():
            # For now, all users have role 'rider'.
            role = 'rider'

            trips = fetchUserTrips(userId)
            for rideId, tripMetaInfo in trips.items():
                # Ride IDs in the table are strings but RideWith GPS IDs are numbers.
                if str(rideId) in existingRides:
                    # Already inserted this trip.
                    continue

                trip = fetchTrip(rideId)

                # Find the route which must be a registered route.
                route = None
                for extra in trip.get('extras', []):
                    # Only show the club's routes.
                    if (extra.get('type') == 'route' and extra.get('id') in routes and
                        'route' in extra):
                        route = extra['route']
                        print('User ' + str(userId) + ': ' + str(user.get('displayName')) +
                              ', ride ' + str(tripMetaInfo['id']) + ' route ' +
                              str(route['id']))
                        break

                if route == None or trip.get('trip') == None or trip['trip'].get('track_points') == None:
                    # Insert a ride where the organization is 'other', meaning
                    # that the user uploaded an unrelated trip. We insert this
                    # so that we don't fetch the trip data again.
                    insertRide(cur, str(rideId), str(userId), None, None, None, None,
                      None, None, region, 'other', None, None)
                    continue

                print("Process ride " + str(rideId))
                # Get the waypoints in the form needed by splitWaypoints, etc.
                waypoints = []
                for point in trip['trip']['track_points']:
                    waypoints.append({ 'longitude': point['x'], 'latitude': point['y'],
                      'timestamp': datetime.fromtimestamp(point['t']).isoformat() })

                startZone, endZone, _ = splitWaypoints(obfuscateRadius, waypoints)

                # TODO: Get the flow from the route.
                flow = None
                flowName = None

                # TODO: Infer the pod.
                inferredPod = None
                inferredPodName = None

                weatherJson = None
                if role == 'rider' or role == 'steward':
                    # For a steward include the weather (at the start waypoint).
                    weatherJson = fetchWeatherJson(startZone[0]['latitude'], startZone[0]['longitude'],
                      accuweatherLocationUrl, accuweatherConditionsUrl, accuweatherApiKey,
                      requests)

                insertRide(cur, rideId, userId, role, flow, flowName,
                  inferredPod, inferredPodName, weatherJson, region, organization,
                  startZone, endZone)
                insertRawWaypoints(cur, rideId, waypoints)

        conn.commit()
        cur.close()

        requestReply = processedReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    return requestReply

def fetchRoutes():
    """
    Fetch all the routes for clubId (defined by the environment variable) from
    the RideWithGPS API. Return a dict where the key is the route ID and the
    value is the route JSON. Throw an exception for error.
    """
    response = requests.get(
      'https://ridewithgps.com/clubs/' + str(clubId) + '/routes.json?version=3&apikey=' +
      apiKey + '&auth_token=' + authToken)
    if response.status_code/100 == 2:
        result = {}
        for route in response.json()['results']:
            result[route['id']] = route
        return result
    else:
        raise ValueError('RideWithGPS API request for routes failed with code {}'.format(response.status_code))

def queryActiveUsers(cur, region, organization):
    """
    Query the enrollments table for all active users in the region and organization.
    Return a dict where the key is the user ID and the value is a JSON with the info.
    """
    sql = """
      SELECT "userId", role, "displayName", email
      FROM {0}
      WHERE active = TRUE AND region = '{1}' AND organization = '{2}'
    """.format(CibicResources.Postgres.UserEnrollments, region, organization)
    cur.execute(sql)
    result = {}
    for user in cur.fetchall():
        result[user[0]] = {
            'role': user[1],
            'displayName': user[2],
            'email': user[3]
        }

    return result

def queryRideIds(cur, region):
    """
    Query the rides table for all rides in the region, disregarding the
    organization which can be CibicResources.Organization or 'other'. Return an
    array of the ride IDs.
    """
    sql = """
      SELECT "rideId"
      FROM {0}
      WHERE region = '{1}'
    """.format(CibicResources.Postgres.Rides, region)
    cur.execute(sql)
    result = []
    for ride in cur.fetchall():
        result.append(ride[0])

    return result

def fetchUserTrips(userId):
    """
    Fetch the meta info for all the trips of userId from the RideWithGPS API.
    Return a dict where the key is the trip ID and the value is the trip JSON.
    Throw an exception for error.
    """
    response = requests.get(
      'https://ridewithgps.com/users/' + str(userId) + '/trips.json?version=2&apikey=' +
      apiKey + '&auth_token=' + authToken)
    if response.status_code/100 == 2:
        result = {}
        for trip in response.json()['results']:
            result[trip['id']] = trip
        return result
    else:
        raise ValueError('RideWithGPS API request for trips failed with code {}'.format(response.status_code))

def fetchTrip(tripId):
    """
    Fetch the give trip from the RideWithGPS API. Return the JSON list.
    Throw an exception for error.
    """
    response = requests.get(
      'https://ridewithgps.com/trips/' + str(tripId) + '.json?version=3&apikey=' +
      apiKey + '&auth_token=' + authToken)
    if response.status_code/100 == 2:
        return response.json()
    else:
        raise ValueError('RideWithGPS API request for trip failed with code {}'.format(response.status_code))

def insertRide(cur, rideId, userId, role, flow, flowName,
               inferredPod, inferredPodName, weatherJson, region, organization, startZone, endZone):
    """
    Insert into the rides table. rideId and userId must be None or a str (not number).
    """
    if startZone == None or endZone == None:
        # This is for inserting rides where organization is 'other'.
        sql = """
              INSERT INTO {}("rideId", "userId", "role", "flow", "flowName",
                             "inferredPod", "inferredPodName", "weatherJson", region, organization)
              VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
              """.format(CibicResources.Postgres.Rides)
        cur.execute(sql, (rideId, userId, role, flow, flowName,
                          inferredPod, inferredPodName, weatherJson, region, organization))
        return

    # generate start / end geometry
    cLat1, cLon1, rad1 = obfuscateWaypoints(startZone)
    cLat2, cLon2, rad2 = obfuscateWaypoints(endZone)
    sql = """
          INSERT INTO {}("rideId", "startTime", "endTime", "userId", "role", "flow", "flowName",
                         "inferredPod", "inferredPodName", "weatherJson", region, organization, "startZone", "endZone")
          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  ST_Buffer(ST_GeomFromText('{}',4326)::geography,
                              {},'quad_segs=16')::geometry,
                  ST_Buffer(ST_GeomFromText('{}',4326)::geography,
                              {},'quad_segs=1')::geometry
          )
          """.format(CibicResources.Postgres.Rides,
                      wktPoint(cLat1, cLon1), rad1,
                      wktPoint(cLat2, cLon2), rad2)
    cur.execute(sql, (rideId, startZone[0]['timestamp'], endZone[-1]['timestamp'], userId, role, flow, flowName,
                      inferredPod, inferredPodName, weatherJson, region, organization))

def wktPoint(lat, lon):
    return 'POINT({} {})'.format(lon, lat)

def insertRawWaypoints(cur, rideId, waypoints):
    sql = """
            INSERT INTO {} ("rideId", coordinate, timestamp, idx, zone, "pointJson")
            VALUES %s
          """.format(CibicResources.Postgres.WaypointsRaw)
    values = list((rideId, makeSqlPoint(wp['latitude'], wp['longitude']),
                    wp['timestamp'], wp['originalIdx'], wp['zone'],
                    # Cache the JSON of the point with the timestamp.
                    '[' + str(wp['longitude']) + ', ' + str(wp['latitude']) + ', 0, "' + wp['timestamp'] + '"]')
                  for wp in waypoints)
    extras.execute_values(cur, sql, values)

def makeSqlPoint(lat, lon):
    return str(lon) + ', ' + str(lat)
