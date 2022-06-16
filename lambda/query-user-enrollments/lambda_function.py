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
          SELECT "userId", "role", "active", "displayName", "email", "outwardFlowName", "outwardFlowId", "returnFlowName", "returnFlowId",
            "outwardPodName", "outwardPodId", "returnPodName", "returnPodId",
            "homeAddressText", "homeFullAddress", "homeZipCode", "homeCoordinate", "homeGeofenceRadius",
            "workAddressText", "workFullAddress", "workZipCode", "workCoordinate", "workGeofenceRadius"
          FROM {}
        """.format(CibicResources.Postgres.UserEnrollments)
        cur.execute(sql)

        enrollmentsResponse = []
        for enrollment in cur.fetchall():
            enrollmentsResponse.append({
              'userId': enrollment[0],
              'role': enrollment[1],
              'active': enrollment[2],
              'displayName': enrollment[3],
              'email': enrollment[4],
              'outwardFlowName': enrollment[5],
              'outwardFlowId': enrollment[6],
              'returnFlowName': enrollment[7],
              'returnFlowId': enrollment[8],
              'outwardPodName': enrollment[9],
              'outwardPodId': enrollment[10],
              'returnPodName': enrollment[11],
              'returnPodId': enrollment[12],
              'home': {
                'addressText': enrollment[13],
                'fullAddress': enrollment[14],
                'zipCode': enrollment[15],
                'coordinate': enrollment[16],
                'geofenceRadius': enrollment[17]
              },
              'work': {
                'addressText': enrollment[18],
                'fullAddress': enrollment[19],
                'zipCode': enrollment[20],
                'coordinate': enrollment[21],
                'geofenceRadius': enrollment[22]
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
