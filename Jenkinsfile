#!groovy
@Library('mapillary-pipeline') _
com.mapillary.pipeline.Pipeline.builder(this, steps)
    .defaultPipeline()
    .skipUnitStage()
    .skipSystemStage()
    .build()
    .execute()
