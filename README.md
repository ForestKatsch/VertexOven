
# Vertex Oven for Blender

![](https://raw.githubusercontent.com/ForestKatsch/VertexOven/master/media/featured-image.png)
[**Vertex Oven**](https://github.com/ForestKatsch/VertexOven/releases) bakes ambient occlusion directly to vertex colors (and, optionally, vertex groups.)

Vertex Oven works with Blender 2.80 and up.

![The operator settings as of v0.1.1](https://raw.githubusercontent.com/ForestKatsch/VertexOven/master/media/operator-settings.png)

## Features:

* Bakes ambient occlusion to vertex colors and vertex groups
* Bake to multiple objects at once

# Installation

* Download the file that looks like `vertex-oven-<version>.zip` from the [Releases page](https://github.com/ForestKatsch/VertexOven/releases).
* Open Blender's **Preferences** window and navigate to the **Add-ons** tab
* Click the **Install** button and select the zip file you downloaded.
* Enable **Vertex Oven**

# How to Use

With a mesh object active, open the Object menu in the 3D view, select Vertex Oven, and select Bake Vertex Ambient Occlusion.
When you're happy with the settings, click OK.
Baking will take anywhere from a few seconds to multiple minutes; keep an eye on the status on the left side of Blender's statusbar.

To use the vertex colors in a shader, add an **Attribute** node and type in the name of the vertex color layer (**Ambient Occlusion** by default.)
Use the **Fac** output as the ambient occlusion value; by default, this ranges from `0.0` (fully occluded) to `1.0` (no occlusion.)
![Using Vertex Colors in an Eevee or Cycles shader](https://raw.githubusercontent.com/ForestKatsch/VertexOven/master/media/attribute-node-shader.png)

For a quick preview of vertex colors, you can also enter **Vertex Paint** mode (Ctrl-Tab and select the top option.)

# Changelog

## v0.1.4

* Relicensed to GPL v3 in preparation for release.
* Added elapsed time readout (printed out to the console.)
* Fixed issue that could occur when not in Object Mode.

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

GPL v3 license; see `LICENSE` file.
