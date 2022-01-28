from common.cibic_common import *
import os
import psycopg2

pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_PPOSTGRES_SERVER']
routesTable = os.environ['ENV_VAR_POSTGRES_TABLE_ROUTES']
snappedWpTable = os.environ['ENV_VAR_POSTGRES_TABLE_SNAPPED_WPS']

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
                    print('fetched ride data {}'.format(rideData))
                    return lambdaReply(200, rideData)
                else:
                    print('no ride with id {} found'.format(rideId))
                    return lambdaReply(404, 'not found')

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
          """.format(routesTable, snappedWpTable, rideId)
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
