#!groovy
@Library('mapillary-pipeline') _
com.mapillary.pipeline.Pipeline.builder(this, steps)
    .withBuildApplicationStage(["osx", "windows"])
    .build()
    .execute()
