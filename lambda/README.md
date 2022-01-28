# Look around

* `_template` -- contains simple template for a lambda function;
Starting up with a new lambda should be as easy as running:

```
rsync -av _template/ my-lambda
```

* `upload.sh` -- helper for deploying your lambda in AWS;
  **NOTE:** If you use custom dependencies, list them in `<your-lambda-folder>/requirements.txt` and you'll need Docker to deploy your lambda (see `upload.sh`).

* `common` -- contains single python file with helpers that are imported by lambdas;

## Note on lambda dependencies

If your lambda requires modules, not provided by AWS lambda environment, you can utilize lambda layers. [Here](https://dev.to/razcodes/how-to-create-a-lambda-layer-in-aws-106m) is a simple quick-start example on how to prepare, upload and setup a lambda layer.
