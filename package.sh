#!/usr/bin/env bash
# -------------------------------------------------------------------------------
#
# -------------------------------------------------------------------------------
#

######################
# exit_error()
function exit_error() {
    echo "** Falure: $1"
    exit 1
}
echo "* Begin packaging ebs_snapshot_lambda for AWS Lambda."
# Validate the tools we need are installed.
ZIP=`which zip`  || exit_error "Can't find the \'zip\' utility"
PIP=`which pip`  || exit_error "Can't find the Python \'pip\' utility"

if [ -f "ebs_snapshot_lambda.zip" ]; then
    rm -f ebs_snapshot_lambda.zip
fi

if [ ! -d "pytz" ]; then
    ${PIP} install  --target=`pwd` pytz || exit_error "Can't pytz via pip"
fi

${ZIP} -q -u -r ebs_snapshot_lambda.zip setup.cfg pytz* ebs_snapshot_lambda.py ebs_snapshot_lambda.ini || exit_error "Creating or updating zip file failed"

echo "* End packaging ebs_snapshot_lambda for AWS Lambda."

