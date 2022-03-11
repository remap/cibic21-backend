from common.cibic_common import *
import os
import psycopg2
import arrow # for parsing arbitrary timestamps from URL request parameters
import urllib

pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']

def lambda_handler(event, context):
    try:
        print (event)
        if event['requestContext']['resourcePath'] == '/ride/get':
            if 'rideId' in event['queryStringParameters']:
                rideId = event['queryStringParameters']['rideId']
                # fetch ride from postgres as GeJSON
                print('fetching ride {}...'.format(rideId))
                rideData = fetchRide(rideId)
                if rideData:
                    return lambdaReply(200, rideData)
                else:
                    print('no ride with id {} found'.format(rideId))
                    return lambdaReply(404, 'not found')

        if event['requestContext']['resourcePath'] == '/ride/query':
            if 'startTime' in event['queryStringParameters'] and 'endTime' in event['queryStringParameters']:
                startTime = parseDatetime(event['queryStringParameters']['startTime'])
                endTime = parseDatetime(event['queryStringParameters']['endTime'])

                if not startTime or not endTime:
                    return lambdaReply(420, 'bad format for startTime/endTime parameters')

                if 'idsOnly' in event['queryStringParameters']:
                    rides = queryRidesSimple(startTime, endTime)
                else:
                    rides = queryRidesRich(startTime, endTime)
                print('fetched {} rides'.format(len(rides)))
                return lambdaReply(200, rides)
            else:
                return malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

def fetchRide(rideId):
    sql = """
            SELECT json_build_object(
                    'type', 'FeatureCollection',
                    'features', array_to_json(feature_list),
                    'properties', json_build_object(
                                    'rideId', rid,
                                    'startTime', start_time,
                                    'stopTime', stop_time
                                  )
                    )
            FROM (SELECT array[json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(arr[1])::json
                               ),
                               json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(arr[2])::json
                               ),
                               json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(arr[3])::json)
                               ] AS feature_list,
                               rid, start_time, stop_time
                  FROM (SELECT array[ride."startZone",
                                     ride."endZone",
                                     ST_MakeLine(array_agg(wp.coordinate::geometry ORDER BY "snapIdx"))] AS arr,
                               ride."rideId" AS rid,
                               ride."startTime" AS start_time,
                               ride."endTime" AS stop_time
                        FROM {} AS ride
                        INNER JOIN {} AS wp
                        ON ride."rideId" = wp."rideId"
                        WHERE ride."rideId" = '{}'
                        GROUP BY ride."rideId") AS geo) AS feature_collection;
          """.format(CibicResources.Postgres.Rides, CibicResources.Postgres.WaypointsSnapped, rideId)
    conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                            user=pgUsername, password=pgPassword)
    cur = conn.cursor()
    cur.execute(sql)

    rideData = None
    results = cur.fetchall()
    if len(results):
        print('ride fetched {}'.format(results[0]))
        rideData = results[0][0]

    conn.commit()
    cur.close()

    return rideData

def parseDatetime(ss):
    try:
        dt = arrow.get(urllib.parse.unquote(ss))
        return dt.datetime
    except:
        return None

def queryRidesSimple(startTime, endTime):
    sql = """
            SELECT ride."rideId"
            FROM {0} as ride
            WHERE ride."startTime" BETWEEN '{1}' AND '{2}' AND ride."endTime" BETWEEN '{1}' AND '{2}'
          """.format(CibicResources.Postgres.Rides, startTime, endTime)
    conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                        user=pgUsername, password=pgPassword)
    cur = conn.cursor()
    cur.execute(sql)

    rides = []
    for r in cur.fetchall():
        rides.append(r[0])
    conn.commit()
    cur.close()

    return rides


def queryRidesRich(startTime, endTime):
    sql = """
            SELECT json_build_object(
                    'type', 'FeatureCollection',
                    'features', array_to_json(feature_list),
                    'properties', json_build_object(
                                    'rideId', rid,
                                    'startTime', start_time,
                                    'stopTime', stop_time
                                  )
                    )
            FROM (SELECT array[json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(arr[1])::json
                               ),
                               json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(arr[2])::json
                               ),
                               json_build_object(
                                'type', 'Feature',
                                'geometry', ST_AsGeoJSON(arr[3])::json)
                               ] AS feature_list,
                               rid, start_time, stop_time
                  FROM (SELECT array[ride."startZone",
                                     ride."endZone",
                                     ST_MakeLine(array_agg(wp.coordinate::geometry ORDER BY "snapIdx"))] AS arr,
                               ride."rideId" AS rid,
                               ride."startTime" AS start_time,
                               ride."endTime" AS stop_time
                        FROM {0} AS ride
                        INNER JOIN {1} AS wp
                        ON ride."rideId" = wp."rideId"
                        WHERE ride."startTime" BETWEEN '{2}' AND '{3}' AND ride."endTime" BETWEEN '{2}' AND '{3}'
                        GROUP BY ride."rideId") AS geo) AS feature_collection;
          """.format(CibicResources.Postgres.Rides, CibicResources.Postgres.WaypointsSnapped,
                    startTime.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"),
                    endTime.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"))
    conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                            user=pgUsername, password=pgPassword)
    cur = conn.cursor()
    cur.execute(sql)

    rides = []
    for r in cur.fetchall():
        rides.append(r[0])
    conn.commit()
    cur.close()

    return rides
