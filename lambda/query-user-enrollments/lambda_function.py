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
          SELECT "userId", "role", "outwardFlowName", "outwardFlowId", "returnFlowName", "returnFlowId",
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
              'outwardFlowName': enrollment[2],
              'outwardFlowId': enrollment[3],
              'returnFlowName': enrollment[4],
              'returnFlowId': enrollment[5],
              'outwardPodName': enrollment[6],
              'outwardPodId': enrollment[7],
              'returnPodName': enrollment[8],
              'returnPodId': enrollment[9],
              'home': {
                'addressText': enrollment[10],
                'fullAddress': enrollment[11],
                'zipCode': enrollment[12],
                'coordinate': enrollment[13],
                'geofenceRadius': enrollment[14]
              },
              'work': {
                'addressText': enrollment[15],
                'fullAddress': enrollment[16],
                'zipCode': enrollment[17],
                'coordinate': enrollment[18],
                'geofenceRadius': enrollment[19]
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
