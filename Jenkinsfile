#!groovy
@Library('mapillary-pipeline') _
com.mapillary.pipeline.Pipeline.builder(this, steps)
    .withBuildDockerImageStage()
    .withIntegrationStage()
    .withBuildApplicationStage(["osx-10-12", "win"])
    .build()
    .execute()
