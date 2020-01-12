
# Vertex Oven for Blender

[**Vertex Oven**](https://github.com/ForestKatsch/vertex-oven/releases) bakes ambient occlusion directly to vertex colors (and, optionally, vertex groups.)

Vertex Oven works with Blender 2.80 and up.

![The operator settings as of v0.1.1](https://raw.githubusercontent.com/ForestKatsch/vertex-oven/master/media/operator-settings.png)

## Features:

* Bakes ambient occlusion to vertex colors and vertex groups
* Bake to multiple objects at once

## Installation

* Download the file that looks like `vertex-oven-<version>.zip` from the [Releases page](https://github.com/ForestKatsch/vertex-oven/releases).
* Open Blender's **Preferences** window and navigate to the **Add-ons** tab
* Click the **Install** button and select the zip file you downloaded.
* Enable **Vertex Oven**

## Usage

With a mesh object active, open the Object menu in the 3D view, select Vertex Oven, and select Bake Vertex Ambient Occlusion.
When you're happy with the settings, click OK.
Baking will take anywhere from a few seconds to multiple minutes; keep an eye on the status on the left side of Blender's statusbar.

# Changelog

## v0.1.3

* New feature: bake to selected objects or active object (existing behavior)

## v0.1.2

* Fixed normal matrix multiplication issue

## v0.1.1

* Fixed issue that could occur when Blender called functions in an unexpected order.
* Fixed incorrect invocation of class methods.
* Fixed missing icon issue occurring with Blender 2.80

## v0.1.0

First release.

# License

MIT license; see `LICENSE` file.
