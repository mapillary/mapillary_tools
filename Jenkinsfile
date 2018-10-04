#!groovy
@Library('mapillary-pipeline') _
com.mapillary.pipeline.Pipeline.builder(this, steps)
    .withBuildStage()
    .withReleaseOsxStage()
    .withReleaseWindowsStage()
    .withPublishStage()
    .build()
    .execute()
