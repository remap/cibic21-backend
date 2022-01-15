LAMBDA_NAME=$1
LAMBDA_FOLDER=$2
DIR=`pwd`

if [ $# -ne 2 ]
  then
    echo "Must provide LAMBDA_NAME and LAMBDA_FOLDER arguments"
    exit 1
fi

cd $LAMBDA_FOLDER

if [ -f "requirements.txt" ]
then
    # package lambda with dependencies
    docker run --rm -v `pwd`:/lambda peetonn/fssi2019-lambda-packager:latest
    zip -g -X -r function.zip * -x "*.pyc" -x "*.txt"
else
    zip -X -r function.zip * -x "*.pyc"
fi

cd $DIR
echo "Uploading code from ${LAMBDA_FOLDER} to lambda named ${LAMBDA_NAME}..."
aws lambda update-function-code --function-name $LAMBDA_NAME --zip-file fileb://$LAMBDA_FOLDER/function.zip
rm $LAMBDA_FOLDER/function.zip
