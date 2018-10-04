#!groovy
@Library('mapillary-pipeline') _
com.mapillary.pipeline.Pipeline.builder(this, steps)
    .withBuildStage()
    .withReleaseWindowsStage()
    .withPublishStage()
    .build()
    .execute()
