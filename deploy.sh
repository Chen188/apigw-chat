REGION=cn-northwest-1
BUCKET=apigw-chat-dev-deployment
PROFILE=default

chalice package --merge-template resources.json out --profile $PROFILE
aws cloudformation package  --template-file out/sam.json --s3-bucket $BUCKET --output-template-file out/template.yml --region $REGION --profile $PROFILE
aws cloudformation deploy --template-file out/template.yml --stack-name APIGWChat --capabilities CAPABILITY_IAM  --region $REGION --profile $PROFILE