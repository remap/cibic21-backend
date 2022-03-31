# This Lambda for the API to query the Posgres table and return user enrollments.

from common.cibic_common import *
import os
import psycopg2

pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']

def lambda_handler(event, context):
    requestReply = {}
    err = ''

    try:
        print('query-user-enrollments event data: ' + str(event))

        conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                user=pgUsername, password=pgPassword)
        cur = conn.cursor()

        sql = """
          SELECT "username", "role",
            "homeAddressText", "homeFullAddress", "homeZipCode", "homeCoordinate", "homeGeofenceRadius",
            "workAddressText", "workFullAddress", "workZipCode", "workCoordinate", "workGeofenceRadius"
          FROM {}
        """.format(CibicResources.Postgres.UserEnrollments)
        cur.execute(sql)

        enrollmentsResponse = []
        for enrollment in cur.fetchall():
            enrollmentsResponse.append({
              'username': enrollment[0],
              'role': enrollment[1],
              'home': {
                'addressText': enrollment[2],
                'fullAddress': enrollment[3],
                'zipCode': enrollment[4],
                'coordinate': enrollment[5],
                'geofenceRadius': enrollment[6]
              },
              'work': {
                'addressText': enrollment[7],
                'fullAddress': enrollment[8],
                'zipCode': enrollment[9],
                'coordinate': enrollment[10],
                'geofenceRadius': enrollment[11]
              }
            })

        conn.commit()
        cur.close()

        print("Returning {} enrollments".format(len(enrollmentsResponse)))
        requestReply = lambdaReply(200, enrollmentsResponse)
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return requestReply
