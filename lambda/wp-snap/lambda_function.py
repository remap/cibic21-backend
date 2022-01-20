from common.cibic_common import *
import os
import psycopg2
from psycopg2 import extras # for fast batch insert, see https://www.psycopg.org/docs/extras.html#fast-exec

pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_PPOSTGRES_SERVER']
routesTable = os.environ['ENV_VAR_POSTGRES_TABLE_ROUTES']
waypointsTable = os.environ['ENV_VAR_POSTGRES_TABLE_WPS']

# lambda is triggered by SNS notification
# SNS message expected payload:
# { "id": "<ride-id>" }
def lambda_handler(event, context):
    try:
        print (event)
        for rec in event['Records']:
            payload = json.loads(rec['Sns']['Message'])
            if 'id' in payload:
                print ('route snapping for ride id {}'.format(payload['id']))

                conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                        user=pgUsername, password=pgPassword)
                cur = conn.cursor()

                # retrieve waypoints
                waypoints = selectWaypoints(cur, payload['id'])

                conn.commit()
                cur.close()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

def selectWaypoints(cur, rideId):
    sql = """
          SELECT * FROM {}
          WHERE "rideId"=%s AND zone=%s
          """.format(waypointsTable)
    try:
        cur.execute(sql, (rideId, "main"))
        waypoints = []
        for wp in cur.fetchall():
            # lon,lat = wp[1]
            waypoints.append({
                'coordinate': wp[1], # { 'latitude': lat, 'longitude': lon},
                'timestamp': wp[2],
                'roadType': wp[3],
                'speed': wp[4],
                'distance': wp[5],
                'speedLimit': wp[6]
            })
        print(waypoints)
        print('{} waypoints fetched'.format(len(waypoints)))
        return waypoints
    except (Exception, psycopg2.Error) as error:
        print("error fetching data from PostgreSQL table", error)
    return []
