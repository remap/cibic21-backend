# This lambda runs periodically to infer the pod for a ride whose inferredPod is
# NULL. If the inferred pod cannot be determined, set it to 'unknown' so that we
# don't try to infer again.

from common.cibic_common import *
import os
import psycopg2
from datetime import datetime, timedelta

pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
jointPointRadius = int(os.environ['ENV_VAR_JOIN_POINT_RADIUS'])

def lambda_handler(event, context):
    now = datetime.now().astimezone()

    try:
        if not 'rideIds' in event:
            return malformedMessageReply()

        conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                user=pgUsername, password=pgPassword)
        cur = conn.cursor()

        # Get all rides which don't have an inferred pod yet.
        sql = """
SELECT "rideId", "startTime", "endTime", flow, role, pod, "podName", region, organization
  FROM {0}
  WHERE "inferredPod" IS NULL;
        """.format(CibicResources.Postgres.Rides)
        cur.execute(sql)
        rides = cur.fetchall()

        for ride in rides:
            rideId = ride[0]
            startTime = ride[1]
            endTime = ride[2]
            flow = ride[3]
            role = ride[4]
            pod = ride[5]
            podName = ride[6]
            region = ride[7]
            organization = ride[8]

            print('Inferring pod for rideId ' + rideId)

            if role == 'steward':
                if pod != None:
                    # For the steward, set the inferredPod to the pod.
                    updateInferredPod(cur, rideId, pod, podName)
                else:
                    updateInferredPod(cur, rideId, 'unknown', 'unknown')
                continue

            if (now - endTime) < timedelta(days=1):
                # The ride ended within the past day. Give more time for all
                # possible matching steward rides to be uploaded.
                continue

            # Get all steward rides for the same flow, region and organization where times overlap.
            # Exclude rides with null pod or join points.
            sql = """
SELECT "rideId", pod, "podName", "flowJoinPointsJson"
  FROM {0}
  WHERE role = 'steward' AND flow = '{1}' AND region = '{2}' AND organization = '{3}' AND
        "endTime" > '{4}' AND "startTime" < '{5}' AND pod IS NOT NULL AND
        "flowJoinPointsJson" IS NOT NULL;
            """.format(CibicResources.Postgres.Rides, flow, region, organization,
                       startTime, endTime)
            cur.execute(sql)
            stewardRides = cur.fetchall()
            if len(stewardRides) == 0:
                print('There are no matching steward rides for rideId ' + rideId)
                updateInferredPod(cur, rideId, 'unknown', 'unknown')
                continue

            # Check if all steward rides have the same pod.
            inferredPod = stewardRides[0][1]
            inferredPodName = stewardRides[0][2]
            for i in range(1, len(stewardRides)):
                joinPoints = stewardRides[i][3]
                if stewardRides[i][1] != inferredPod and len(joinPoints) > 0:
                    # Found a steward ride with a different pod, which has join points to examine.
                    inferredPod = None
                    inferredPodName = None
                    break

            # TODO: For Buenos Aires, is the pod name just the steward userId?
            if inferredPod != None:
                # There is only one choice, so use it.
                print("inferredPod " + str(inferredPod))
                updateInferredPod(cur, rideId, inferredPod, inferredPodName)
                continue

            # There are steward rides with different pods. Must choose.
            closestDistanceToSteward = None
            for stewardRide in stewardRides:
                stewardRideId = stewardRide[0]
                stewardPod = stewardRide[1]
                stewardPodName = stewardRide[2]
                joinPoints = stewardRide[3]
                if len(joinPoints) == 0:
                    continue

                finalJoinPoint = joinPoints[-1]
                # Get the time that the steward left the join point.
                finalJoinPointLeaveTime = getPointLeaveTime(
                  cur, stewardRideId, finalJoinPoint['lat'], finalJoinPoint['long'])
                if finalJoinPointLeaveTime == None:
                    # Already printed the error.
                    continue

                # Find the rider's waypoint at finalJoinPointLeaveTime and get
                # its distance to the finalJoinPoint.
                sql = """
SELECT ST_Distance(ST_SetSRID(coordinate::geometry, 4326)::geography, ST_SetSRID(ST_Point({1}, {2}), 4326)::geography) AS distance
	FROM {0}
	WHERE "rideId" = '{3}' AND "timestamp" >= '{4}'
	ORDER BY "timestamp"
	LIMIT 1;
                """.format(CibicResources.Postgres.WaypointsRaw,
                           finalJoinPoint['long'], finalJoinPoint['lat'], rideId,
                           finalJoinPointLeaveTime)
                cur.execute(sql)
                match = cur.fetchone()
                if match == None:
                    # We don't expect this.
                    distanceToSteward = 1000000
                else:
                    distanceToSteward = match[0]

                if closestDistanceToSteward == None or distanceToSteward < closestDistanceToSteward:
                    # This steward is closer. Use its pod.
                    closestDistanceToSteward = distanceToSteward
                    inferredPod = stewardPod
                    inferredPodName = stewardPodName

            print("inferredPod " + str(inferredPod))
            if inferredPod != None:
                updateInferredPod(cur, rideId, inferredPod, inferredPodName)
            else:
                updateInferredPod(cur, rideId, 'unknown', 'unknown')

        conn.commit()
        cur.close()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

def updateInferredPod(cur, rideId, inferredPod, inferredPodName):
    """
    Update the inferred pod for the rideId.
    """
    sql = """
UPDATE {0} SET "inferredPod" = '{1}', "inferredPodName" = '{2}'
  WHERE "rideId" = '{3}';
    """.format(CibicResources.Postgres.Rides, inferredPod, inferredPodName,
               rideId)
    cur.execute(sql)

def getPointLeaveTime(cur, rideId, lat, lon):
    """
    Get the waypoints for the ride and return the time when leaving the point
    defined by lat, lon. If error, print it and return None.
    """
    # Get the waypoints which are 'close' to the point.
    sql = """
SELECT "timestamp", ST_Distance(ST_SetSRID(coordinate::geometry, 4326)::geography, ST_SetSRID(ST_Point({1}, {2}), 4326)::geography) AS distance
	FROM {0}
	WHERE "rideId" = '{3}'
	ORDER BY "timestamp" DESC;
    """.format(CibicResources.Postgres.WaypointsRaw, lon, lat, rideId)
    cur.execute(sql)
    waypoints = cur.fetchall()
    if len(waypoints) == 0:
        print('There are no waypoints for rideId ' + rideId)
        return None

    closest = waypoints[0][1]
    timeOfClosest = waypoints[0][0]
    for waypoint in waypoints:
        distance = waypoint[1]
        if distance <= jointPointRadius:
            # The waypoints are in descending time, so this is the latest time
            # when the rider was at the join point.
            return waypoint[0]

        if distance < closest:
            # Also find the time of the closest point in case none are near the point.
            closest = distance
            timeOfClosest = waypoint[0]

    # There were no points within jointPointRadius of the point, so use the closest.
    return timeOfClosest
