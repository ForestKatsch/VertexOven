# Blender Vertex Oven addon
# Copyright (C) 2019 Forest Katsch (forestcgk@gmail.com)
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

bl_info = {
    "name": "Vertex Oven",
    "description": "Bake ambient occlusion straight to vertex colors",
    "author": "Forest Katsch",
    "version": (0, 1, 3),
    "blender": (2, 80, 0),
    "location": "3D View > Object > Vertex Oven",
    "warning": "Warning: this addon is still young, and problems may occur. Make sure you've backed up your Blender file first.",
    "support": "COMMUNITY",
    "category": "Mesh"
}

import numpy as np

import math
import mathutils

from mathutils.bvhtree import BVHTree
from bpy.props import StringProperty, EnumProperty, FloatProperty
from bpy.types import Operator

import bpy

class BakeError(Exception):

    def __init__(self, message):
        self.message = message

class BakeOptions:

    def __init__(self, valid_keys=None):
        self.valid_keys = self.get_valid_keys()
        
        self.options = {}
        
    def get_valid_keys(self):
        return []
    
    def __getattr__(self, key):
        return self.options[key]
        
    def from_operator(self, operator):

        print(self.options)

        for key in self.valid_keys:
            self.options[key] = getattr(operator, key)

class BakeOptionsAO(BakeOptions):

    def get_valid_keys(self):
        return [
            "bake_receive_objects",
            
            "bake_cast_objects",
            "include_self",
            
            "bake_to_color",
            "color_layer_name",
            "color_invert",
            
            "bake_to_group",
            "group_name",
            "weight_invert",
            
            "max_distance",
            "power",
            "seed",
            "sample_count",
            
            "jitter",
            "jitter_fraction"
        ]
        
# This never worked right.
#class ProgressWidget(object):
#    # Seconds.
#    update_every = 0.2
#
#    widget_visible = False
#
#    timer = None
#
#    context = None
#
#    @staticmethod
#    def update_widget():
#
#        for area in bpy.context.screen.areas:
#            area.tag_redraw()
#
#        return ProgressWidget.update_every
#
#    @staticmethod
#    def draw(self, context):
#        if ProgressWidget.get_progress(context) < 100:
#            self.layout.prop(context.scene, "ProgressWidget_progress", text="Progress", slider=True)
#            self.layout.label(text="UGH FOOBAR")
#        else:
#            ProgressWidget.hide()
#
#    @staticmethod
#    def create_progress_property():
#        bpy.types.Scene.ProgressWidget_progress = bpy.props.IntProperty(default=0, min=0, max=100, step=1, subtype='PERCENTAGE')
#
#    @staticmethod
#    def set_progress(context, value):
#        
#        if ProgressWidget.widget_visible:
#            context.scene.ProgressWidget_progress = value
#            
#            for area in bpy.context.screen.areas:
#                if area.type == 'INFO':
#                    area.tag_redraw()
#
#
#    @staticmethod
#    def get_progress(context):
#        if ProgressWidget.widget_visible:
#            return context.scene.ProgressWidget_progress
#        else:
#            return 0
#
#    @staticmethod
#    def show(context):
#        
#        if not ProgressWidget.widget_visible:
#            ProgressWidget.create_progress_property()
#
#            bpy.types.STATUSBAR_HT_header.append(ProgressWidget.draw)
#            
#            ProgressWidget.widget_visible = True
#
#            ProgressWidget.set_progress(context, 0)
#            
#            # Start a timer to redraw ourselves.
#            bpy.app.timers.register(ProgressWidget.update_widget)
#
#    @staticmethod
#    def hide():
#        bpy.types.STATUSBAR_HT_header.remove(ProgressWidget.draw)
#        
#        bpy.app.timers.unregister(ProgressWidget.update_widget)
#
#        ProgressWidget.widget_visible = False

class BakeAO:
    """The primary bake class. Users must run `bake(vertices=<>)` and `finish()` manually."""

    def __init__(self, options, context):
        self.options = options
        self.context = context
        
        # The object we're baking at the moment.
        self.active_object = None
        
        # The objects that receive ambient occlusion
        self.bake_receive_objects = []

        # The objects that contribute to ambient occlusion on the receiving objects
        self.bake_cast_objects = []

        # The vertex we're on. This goes up until it reaches `len(mesh.vertices)`.
        self.last_vertex_index = 0

        # self.ao_data is a dictionary of {vertex_index: ambient occlusion}
        self.ao_data = {}

        # Start baking.
        self.start()

    # Returns a value within the range 0..100
    def get_progress_percentage(self):
        return (self.last_vertex_index / len(self.active_mesh.vertices)) * 100

    @classmethod
    def random_vector(cls):
        """
        Generates a random 3D unit vector (direction) with a uniform spherical distribution
        Algo from http://stackoverflow.com/questions/5408276/python-uniform-spherical-distribution
        :return:
        """
        
        phi = np.random.uniform(0,np.pi*2)
        costheta = np.random.uniform(-1,1)
    
        theta = np.arccos(costheta)
        x = np.sin(theta) * np.cos(phi)
        y = np.sin(theta) * np.sin(phi)
        z = np.cos(theta)
        return mathutils.Vector((x,y,z))

    def occlusion_from_distance(self, distance, max_distance=10, power=0.5):
        """Given a distance, returns the "occlusion". This is not physically correct, but looks approximately correct."""
        return math.pow(min(1.0, max(0.0, 1.0 - (distance / max_distance))), power)
    
    def distance_to_object(self, position, normal, bvh, matrix_inverse, matrix_inverse_3x3):
        
        normal = matrix_inverse_3x3 @ normal
        position = matrix_inverse @ position
        
        ray = bvh.ray_cast(position, normal, self.options.max_distance)
    
        if not ray[0]:
            return -1
    
        return ray[3]

    def jitter_vertex(self, vertex, sample):
        mesh = self.active_mesh

        if not self.options.jitter:
            return vertex.co

        # Valid faces that we can jitter along.
        polygons = []
        
        for poly in mesh.polygons:
            vertices = poly.vertices

            # Don't bother handling 
            if len(vertices) > 4:
                continue
            
            if vertex.index in vertices:
                polygons.append(poly)

        if len(polygons) == 0:
            return vertex.co

        # The chosen face we'll jitter along.
        poly = polygons[np.random.randint(0, len(polygons))]

        edges = []

        for edge_key in poly.edge_keys:
            edge = mesh.edges[mesh.edge_keys.index(edge_key)]
            if vertex.index in edge.vertices:
                edges.append(edge)

        # This should never happen!
        if len(edges) != 2:
            return vertex.co

        directions = []

        for edge in edges:
            other_vertex = edge.vertices[0]

            if other_vertex == vertex.index:
                other_vertex = edge.vertices[1]

            other_vertex = mesh.vertices[other_vertex]
                
            directions.append(vertex.co - other_vertex.co)

        fraction = self.options.jitter_fraction * 0.5
        
        offset = (directions[0] * (np.random.uniform() * fraction)) + (directions[1] * (np.random.uniform() * fraction))

        return vertex.co + offset
    
    def calculate_vertex_ao(self, vertex):
        """
Returns a value, 0-1, of how occluded this `vertex` is. Samples are taken for each object; the count is
determined by `self.options.sample_count`.
"""
        obj = self.active_object
    
        normal = obj.matrix_world.to_3x3() @ vertex.normal
        position = (obj.matrix_world @ vertex.co) + (normal * 0.0001)
    
        occlusion = 0

        sample_position = position
        
        for i, sample_point in enumerate(self.sample_distribution):

            if self.options.jitter:
                sample_position = position + self.jitter_vertex(vertex, i)
            
            # Make sure the samples are in a hemisphere.
            if sample_point.dot(normal) < 0:
                direction = sample_point.reflect(normal)
            else:
                direction = sample_point
    
            distance = self.options.max_distance
    
            for obj_cache in self.bake_object_cache:
                sample_distance = self.distance_to_object(sample_position, direction, obj_cache[0], obj_cache[1], obj_cache[2])
                
                if sample_distance >= 0:
                    distance = min(sample_distance, distance)
    
            occlusion += self.occlusion_from_distance(distance, self.options.max_distance, self.options.power)
    
        return occlusion / len(self.sample_distribution)

    @classmethod
    def vertex_color_layer_exists(cls, obj, name):
        """Returns `True` if the vertex color layer `name` exists on `obj`."""
        if obj.type != "MESH":
            return False
        
        if not obj.data.vertex_colors or name not in obj.data.vertex_colors:
            return False

        return True

    @classmethod
    def vertex_group_exists(cls, obj, name):
        """Returns `True` if the vertex group `name` exists on `obj`."""
        if obj.type != "MESH":
            return False
        
        if not obj.vertex_groups or name not in obj.vertex_groups:
            return False

        return True

    @classmethod
    def get_bake_objects(cls, context, bake_objects, include_self=True, active_object=None):
        """Returns a list of objects that will be baked, given the `bake_objects` mode."""

        if active_object == None:
            active_object = context.active_object
        
        # Only baking the active object.
        if bake_objects == "active":
            objects = [active_object]

        # Baking only selected objects.
        elif bake_objects == "selected":
            objects = [obj for obj in context.scene.objects if obj.select_get()]
            
        # Baking the entire scene.
        elif bake_objects == "scene":
            objects = context.scene.objects

        else:
            print("Oh no, we've been requested to get bake objects, but `bake_objects` is {}".format(bake_objects))
            return []

        if not include_self:
            objects = [obj for obj in objects if obj != active_object]

        return BakeAO.cull_invalid_objects(objects)
        
    @classmethod
    def cull_invalid_objects(cls, objects):
        """Returns the list `objects` without any invalid objects for baking."""
        
        # First, cull all non-meshes. (Without this step, BVHTree generation straight-up crashes Blender.)
        objects = [obj for obj in objects if obj.type in ["MESH"]]

        # Next, cull objects that are hidden.
        objects = [obj for obj in objects if obj.visible_get()]

        return objects

    def get_vertex_color_layer(self):
        """Returns Blender's `VertexColors` object."""
        
        mesh = self.active_mesh
        name = self.options.color_layer_name
    
        if not mesh.vertex_colors or name not in mesh.vertex_colors:
            layer = mesh.vertex_colors.new()
            layer.name = name
    
            mesh.vertex_colors.active = layer
    
        layer = mesh.vertex_colors[name]
    
        return layer
    
    def get_vertex_group(self):
        """Returns Blender's `VertexGroup` object."""
        obj = self.active_object
        name = self.options.group_name
    
        if not obj.vertex_groups or name not in obj.vertex_groups:
            group = obj.vertex_groups.new()
            group.name = name
    
            obj.vertex_groups.active = group
    
        group = obj.vertex_groups[name]
    
        return group
    
    def apply_vertex_colors(self):
        """Apply `self.ao_data` to the vertex color layer."""
        
        mesh = self.active_mesh
        layer = self.get_vertex_color_layer()
        
        for polygon in mesh.polygons:
            for i, index in enumerate(polygon.vertices):
                vertex = mesh.vertices[index]
                brightness = self.ao_data[vertex.index]

                if self.options.color_invert:
                    brightness = 1 - brightness
                
                loop_index = polygon.loop_indices[i]
                layer.data[loop_index].color = (brightness, brightness, brightness, 1.0)
    
    def apply_vertex_groups(self):
        """Apply `self.ao_data` to the vertex group."""
        group = self.get_vertex_group()
    
        for vertex_index in self.ao_data:
            weight = self.ao_data[vertex_index]
            
            if self.options.weight_invert:
                weight = 1 - weight
                
            group.add([vertex_index], weight, "REPLACE")

    def start(self):
        print("Baking vertex AO...")
        
        options = self.options
        context = self.context
        
        depsgraph = context.evaluated_depsgraph_get()
    
        # Create a set of random samples. This dramatically speeds up baking.
        self.sample_distribution = []

        self.random_values = []

        # Set our seed.
        np.random.seed(self.options.seed)
    
        for i in range(options.sample_count):
            self.sample_distribution.append(BakeAO.random_vector())
            
            self.random_values.append((np.random.uniform(), np.random.uniform()))

        self.bake_receive_objects = BakeAO.get_bake_objects(context, options.bake_receive_objects, True)

        self.start_object(self.bake_receive_objects[0])

    def start_object(self, obj):
        
        options = self.options
        context = self.context
        
        depsgraph = context.evaluated_depsgraph_get()

        # The object to bake.
        self.active_object = obj
        self.active_mesh = self.active_object.data
    
        # Objects that we'll check AO on.
        self.bake_cast_objects = BakeAO.get_bake_objects(context, options.bake_cast_objects, options.include_self, active_object=self.active_object)

        print("{} object(s) contributing to bake of '{}'".format(len(self.bake_cast_objects), self.active_object.name))
    
        # Finally, get all the BVH tree objects from each object.
        self.bake_object_cache = [(BVHTree.FromObject(bake_obj, depsgraph), bake_obj.matrix_world.inverted(), bake_obj.matrix_world.inverted().to_3x3()) for bake_obj in self.bake_cast_objects]

        # Make sure to set our seed here, too.
        np.random.seed(self.options.seed)
        
        return False

    # If possible, switch to baking the next object; returns `True` if no next object exists.
    def start_next_object(self):
        if self.active_object == None:
            return self.start_object(self.bake_receive_objects[0])
        
        new_index = self.bake_receive_objects.index(self.active_object) + 1

        if new_index >= len(self.bake_receive_objects):
            return True

        return self.start_object(self.bake_receive_objects[new_index])

    def bake(self, vertices=-1):
        """Bakes `vertices` number of vertices. If `vertices` is negative, bakes to completion. This function should be called until it returns `True`."""
        
        options = self.options
        context = self.context
        mesh = self.active_mesh

        i = 0
        
        for vertex in mesh.vertices[self.last_vertex_index:]:

            ao_vertex = self.calculate_vertex_ao(vertex)
    
            self.ao_data[vertex.index] = ao_vertex

            self.last_vertex_index += 1

            i += 1
            
            if vertices > 0 and i > vertices:
                return False
            
        self.finish_object()
                
        self.last_vertex_index = 0
        
        return self.start_next_object()

    def finish_object(self):
        options = self.options
        context = self.context

        if options.bake_to_color:
            print("Applying ambient occlusion to vertex color layer '{}'".format(options.color_layer_name))
            
            self.apply_vertex_colors()
            
        if options.bake_to_group:
            print("Applying ambient occlusion to vertex group layer '{}'".format(options.group_name))
            
            self.apply_vertex_groups()
    
        self.ao_data = {}
        
        print("Bake completed on '{}'".format(self.active_object.name))

    def finish(self):
        print("DONE DONE DONE")
        
class MESH_OT_bake_vertex_ao(bpy.types.Operator):
    bl_idname = "mesh.bake_vertex_ao"
    bl_label = "Bake Vertex Ambient Occlusion"
    bl_description = "Bakes ambient occlusion into vertex data for the active mesh"
    bl_options = {"BLOCKING", "UNDO", "PRESET"}

    # Influence
    
    bake_receive_objects: bpy.props.EnumProperty(
        name="Objects Receiving Occlusion",
        description="Select which objects should receive ambient occlusion.",
        items=[
            ("selected", "Selected Objects", "Bakes ambient occlusion to selected objects only", "RESTRICT_SELECT_OFF", 1),
            ("active", "Active Object", "Bakes ambient occlusion to active object only", "OBJECT_DATA", 2),
        ],
        default="active"
    )
        
    bake_cast_objects: bpy.props.EnumProperty(
        name="Objects Casting Occlusion",
        description="Select which objects should contribute to ambient occlusion. Objects that are hidden in the viewport don't cast any occlusion",
        items=[
            ("scene", "Entire Scene", "Use all visible objects in the scene", "SCENE_DATA", 0),
            ("selected", "Selected Objects", "Bakes occlusion from selected objects only", "RESTRICT_SELECT_OFF", 1),
            ("active", "Active Object Only", "Bakes occlusion from active object only", "OBJECT_DATA", 2),
        ],
        default="scene"
    )

    include_self: bpy.props.BoolProperty(
        name="Include Active Object",
        description="Include the active object in ambient occlusion contribution. (This should probably be on.)",
        default=True
    )

    # Bake targets
    
    bake_to_color: bpy.props.BoolProperty(
        name="Vertex Color",
        description="Write ambient occlusion information to a vertex color layer",
        default=True
    )
    
    color_layer_name: bpy.props.StringProperty(
        name="Layer Name",
        description="The name of the vertex color layer to store the ambient occlusion data in. If this layer doesn't exist, it will be created",
        default="Ambient Occlusion"
    )
    
    color_invert: bpy.props.BoolProperty(
        name="Invert Color",
        description="Normally, 1 is fully occluded, and 0 is no occlusion; this option inverts that",
        default=True
    )
    
    bake_to_group: bpy.props.BoolProperty(
        name="Vertex Group",
        description="Write ambient occlusion information to a vertex group",
        default=False
    )

    group_name: bpy.props.StringProperty(
        name="Group Name",
        description="The name of the vertex group to store the ambient occlusion data in. If this layer doesn't exist, it will be created",
        default="Ambient Occlusion"
    )

    weight_invert: bpy.props.BoolProperty(
        name="Invert Vertex Weight",
        description="Normally, 1 is fully occluded, and 0 is no occlusion; this option inverts that",
        default=False
    )
    
    # Ambient Occlusion Options
    
    max_distance: bpy.props.FloatProperty(
        name="Distance",
        description="The maximum distance to cast rays to. Making this smaller will improve performance at the cost of less-accurate occlusion for distant faces",
        unit="LENGTH",
        default=5.0
    )

    power: bpy.props.FloatProperty(
        name="Power",
        description="The strength of the ambient occlusion. Smaller numbers produce darker, larger areas of occlusion",
        default=0.5
    )

    seed: bpy.props.IntProperty(
        name="Seed",
        description="The seed used to generate the random sampling distribution",
        default=0
    )

    sample_count: bpy.props.IntProperty(
        name="Sample Count",
        description="The number of samples to cast per vertex. The total work done is this multiplied by your vertex count; keep this low to improve performance",
        default=32
    )

    jitter: bpy.props.BoolProperty(
        name="Jitter Samples",
        description="Jitter samples across nearby faces to avoid convex vertices from being lit incorrectly",
        default=False
    )

    jitter_fraction: bpy.props.FloatProperty(
        name="Jitter Fraction",
        description="How far each sample should travel towards its neighboring vertices; 1.0 will travel halfway to the neighboring vertex",
        min=0.0,
        max=1.0,
        default=0.5
    )

    # The timer is used to call ourselves while the bake is in-progress.
    _timer = None

    # The `BakeAO` object. Can be `None` or uninitialized at any point.
    _bake = None

    # This is just a utility function that puts text on the left of the statusbar.
    def update_status(self, context, text):
        context.workspace.status_text_set(text)

    def modal(self, context, event):
        
        if event.type in {"ESC"}:  # Cancel
            self.report({"INFO"}, "Bake cancelled. No data was written.")

            self.cancel(context)
            
            return {"CANCELLED"}
        
        elif event.type != "TIMER":
            return {"PASS_THROUGH"}

        if self._bake == None:

            options = BakeOptionsAO()
            options.from_operator(self)
            
            # Start the bake.
            self._bake = BakeAO(options, context)
        
        try:
            # Perform 10000 samples every time before updating.
            is_completed = self._bake.bake(10000 / self.sample_count)

            # Appears in the lower-left corner.
            object_progress = ""

            if len(self._bake.bake_receive_objects) > 1:
                object_progress = " ({}/{}) objects".format(self._bake.bake_receive_objects.index(self._bake.active_object), len(self._bake.bake_receive_objects))

            message = "Baking vertex ambient occlusion: {:03.1f}%".format(self._bake.get_progress_percentage()) + object_progress
                
            self.update_status(context, message)

            print(message)
            
        except BakeError as e:
            self.report({"ERROR"}, e.message)
            
            self.stopped(context)
            
            return {"CANCELLED"}

        # If we're not done yet, drop out now and tell Blender that.
        if not is_completed:
            return {"PASS_THROUGH"}
        
        # Otherwise, if the bake is completed, finish it up and tell Blender we're done.
        self.stopped(context)
            
        self._bake.finish()

        # Send a nice message to the statusbar.
        destination = []

        if self.bake_to_color:
            destination.append(f"vertex color layer '{self.color_layer_name}'")
                
        if self.bake_to_group:
            destination.append(f"vertex group '{self.group_name}'")

        destination = " and ".join(destination)
            
        self.report({"INFO"}, "Bake complete: check {}".format(destination))
        
        return {"FINISHED"}

    def cancel(self, context):
        wm = context.window_manager

        self.stopped(context)

        if self._timer != None:
            wm.event_timer_remove(self._timer)
            self._timer = None

    # This must be called whenever the operation is stopped, or cursor status will be incorrect.
    def stopped(self, context):
        self.update_status(context, None)
        context.window.cursor_set("DEFAULT")

    # Draws a warning symbol and the message in the given `layout`. Optionally, can be made red if `alert` is True.
    def draw_warning_icon(self, layout, message, alert=False):
        row = layout.row()
        
        if alert:
            row.alert = True
            
        row.label(icon="ERROR", text=message)

    # Draws a checkmark and the message in the given `layout`.
    def draw_checkmark_icon(self, layout, message):
        row = layout.row()

        if bpy.app.version <= (2, 81, 0):
            row.label(icon="BLANK1", text=message)
        else:
            row.label(icon="CHECKMARK", text=message)

    # This draws the UI for the "Vertex Color Layer"/"Vertex Group" toggle and their options.
    def draw_bake_target(self, layout, name, enabled_prop, name_prop, invert_prop, exists):
        box = layout.box()
        
        row = box.split(factor=0.35)
        row.prop(self, enabled_prop, text=name)

        bake_target_name = row.row()
        
        bake_target_name.prop(self, name_prop, text="")
        bake_target_name.active = getattr(self, enabled_prop)

        if not getattr(self, enabled_prop):
            return

        if self.bake_receive_objects != "active":
            self.draw_checkmark_icon(box, "'{}' will be created (if necessary) and overwritten".format(getattr(self, name_prop)))
        else:
            if exists:
                self.draw_checkmark_icon(box, "'{}' exists and will be overwritten".format(getattr(self, name_prop)))
            else:
                self.draw_checkmark_icon(box, "'{}' will be created".format(getattr(self, name_prop)))

        box.use_property_split = True
        row = box.column()
        row.prop(self, invert_prop)

    # Draws the primary UI.
    def draw(self, context):
        layout = self.layout
        
        # Receiving objects
        
        layout.separator()
        #layout.label(text="Receiving Objects:")
        
        split = layout.split(factor=0.35)
        split.label(text="Receiving:")
        
        row = split.row(align=True)
        row.prop(self, "bake_receive_objects", text="")

        bake_receive_objects = BakeAO.get_bake_objects(context, self.bake_receive_objects, True)

        if len(bake_receive_objects) > 1:
            split = layout.split(factor=0.35)
            split.label(text="")
        
            split.label(text="{} object{} receiving ambient occlusion bake".format(len(bake_receive_objects), "s" if len(bake_receive_objects) != 1 else ""))

        # Contributing objects
        
        layout.separator()

        split = layout.split(factor=0.35)
        split.label(text="Casting:")
        
        row = split.row(align=True)
        row.prop(self, "bake_cast_objects", text="")
        row.prop(self, "include_self", toggle=True, icon="OBJECT_DATA", text="")
        
        split = layout.split(factor=0.35)
        split.label(text="")
        
        bake_cast_objects = BakeAO.get_bake_objects(context, self.bake_cast_objects, self.include_self)
        split.label(text="{} object{} contributing to bake".format(len(bake_cast_objects), "s" if len(bake_cast_objects) != 1 else ""))

        layout.separator()

        # Bake Target
        layout.label(text="Bake To:")

        obj = context.active_object

        # Vertex Color Layer options
        self.draw_bake_target(layout, "Vertex Color Layer", "bake_to_color", "color_layer_name", "color_invert", exists=BakeAO.vertex_color_layer_exists(obj, self.color_layer_name))
        
        # Vertex Group options
        self.draw_bake_target(layout, "Vertex Group", "bake_to_group", "group_name", "weight_invert", exists=BakeAO.vertex_group_exists(obj, self.group_name))

        if not self.bake_to_color and not self.bake_to_group:
            self.draw_warning_icon(layout, message="Select at least one of 'Vertex Color Layer' and 'Vertex Group'", alert=True)
        else:
            layout.separator()
        # Next up...
        
        layout.label(text="Bake Options:")

        layout.prop(self, "max_distance")
        layout.prop(self, "power")
        layout.prop(self, "sample_count")

        total_sample_count = 0

        for obj in bake_receive_objects:
            total_sample_count += self.sample_count * len(obj.data.vertices)

        across_all = ""

        if len(bake_receive_objects) > 1:
            across_all = " across {} objects".format(len(bake_receive_objects))

        layout.label(text="{:,} samples total".format(total_sample_count) + across_all)

        layout.separator()

        #row = layout.split(factor=0.35)
        #row.prop(self, "jitter")
        #row.prop(self, "jitter_fraction")


    @classmethod
    def poll(cls, context):
        if not context.active_object or context.active_object.type != "MESH":
            return False
        
        if context.active_object not in context.selected_objects:
            return False

        return True
        
    def invoke(self, context, event):
        wm = context.window_manager
        
        return wm.invoke_props_dialog(self, width=400)
    
    def execute(self, context):

        # We need to bake to somewhere.
        if not self.bake_to_color and not self.bake_to_group:
            self.report({"ERROR"}, "Select at least one of 'Vertex Color Layer' and 'Vertex Group'; otherwise, there's nowhere to save the data!")
            return {"CANCELLED"}

        wm = context.window_manager
        wm.modal_handler_add(self)
        
        # This is where the bulk of the work happens.
        self._timer = wm.event_timer_add(time_step=0.1, window=context.window)

        context.window.cursor_set("WAIT")

        #bpy.ops.wm.bake_vertex_ao_progress('INVOKE_DEFAULT')
        return {"RUNNING_MODAL"}

# I was hoping to use this as a popup to display progress, but that didn't work out either.
class WM_OT_bake_vertex_ao_progress(bpy.types.Operator):
    bl_idname = "wm.bake_vertex_ao_progress"
    bl_label = "_"

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def check(self, context):
        return True

    def draw(self, context):
        layout = self.layout
        layout.label("UGH")

# And the menus.
class MESH_MT_vertex_oven(bpy.types.Menu):
    bl_idname = "MESH_MT_vertex_oven"
    bl_label = "Vertex Oven"

    def draw(self, context):
        layout = self.layout
        layout.operator(MESH_OT_bake_vertex_ao.bl_idname)

def menu_func(self, context):
    self.layout.separator()
    self.layout.menu(MESH_MT_vertex_oven.bl_idname)

register_classes = [
    MESH_OT_bake_vertex_ao,
    MESH_MT_vertex_oven,
    #WM_OT_bake_vertex_ao_progress
]

def register():
    for cls in register_classes:
        bpy.utils.register_class(cls)
        
    bpy.types.VIEW3D_MT_object.append(menu_func)

def unregister():
    for cls in register_classes:
        bpy.utils.unregister_class(cls)
        
    bpy.types.VIEW3D_MT_object.remove(menu_func)
