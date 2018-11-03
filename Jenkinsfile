#!groovy
@Library('mapillary-pipeline') _
com.mapillary.pipeline.Pipeline.builder(this, steps)
    .withBuildStage()
    .withIntegrationStage()
    .withBuildApplicationStage()
    .withBuildWindowsApplicationStage()
    .withSignIosStage()
    .withPublishStage()
    .build()
    .execute()
