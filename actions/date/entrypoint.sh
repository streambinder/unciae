#!/bin/bash
echo "::set-output name=datetime::$(date +${FORMAT:-%F})"