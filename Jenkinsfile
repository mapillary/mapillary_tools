#!groovy
@Library('mapillary-pipeline') _
com.mapillary.pipeline.Pipeline.builder(this, steps)
    .withBuildStage()
    .withIntegrationStage()
    .withBuildApplicationStage(["windows", "osx"])
    .withSignIosStage()
    .withPublishStage()
    .build()
    .execute()
