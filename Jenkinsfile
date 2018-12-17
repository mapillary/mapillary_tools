#!groovy
@Library('mapillary-pipeline') _
com.mapillary.pipeline.Pipeline.builder(this, steps)
    .withBuildStage()
    .withIntegrationStage()
    .withBuildApplicationStage(["osx"])
    .withBuildApplicationStage(["windows"])
    .withSignIosStage()
    .withPublishAppStage()
    .build()
    .execute()
