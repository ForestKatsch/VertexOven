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
    "version": (0, 1, 0),
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

    def __init__(self, operator, context):
        self.operator = operator
        self.context = context
        
        # The object we're baking at the moment.
        self.active_object = None
        self.active_mesh = None

        # The objects that contribute to ambient occlusion on `self.active_object`.
        self.bake_objects = []

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
    
    def distance_to_object(self, position, normal, bvh, matrix_inverted):
        
        position = matrix_inverted @ position
        normal = matrix_inverted @ normal
        
        ray = bvh.ray_cast(position, normal, self.operator.max_distance)
    
        if not ray[0]:
            return -1
    
        return ray[3]
    
    def calculate_vertex_ao(self, vertex):
        
        """
Returns a value, 0-1, of how occluded this `vertex` is. Samples are taken for each object; the count is
determined by `self.operator.sample_count`.
"""
        obj = self.active_object
    
        normal = obj.matrix_world @ vertex.normal
        position = (obj.matrix_world @ vertex.co) + (normal * 0.0001)
    
        occlusion = 0
    
        for sample_point in self.sample_distribution:
        
            # Make sure the samples are in a hemisphere.
            if sample_point.dot(normal) < 0:
                direction = sample_point.reflect(normal)
            else:
                direction = sample_point
    
            distance = self.operator.max_distance
    
            for obj_cache in self.bake_object_cache:
                sample_distance = self.distance_to_object(position, direction, obj_cache[0], obj_cache[1])
                
                if sample_distance >= 0:
                    distance = min(sample_distance, distance)
    
            occlusion += self.occlusion_from_distance(distance, self.operator.max_distance, self.operator.power)
    
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
    def get_bake_objects(cls, context, bake_influence_objects, include_self):
        """Returns a list of objects that will be baked, given the `bake_influence_objects` mode."""
        
        # Only baking the active object.
        if bake_influence_objects == "active":
            objects = [context.active_object]

        # Baking only selected objects.
        elif bake_influence_objects == "selected":
            objects = [obj for obj in context.scene.objects if obj.select_get()]
            
        # Baking the entire scene.
        elif bake_influence_objects == "scene":
            objects = context.scene.objects

        else:
            print("Oh no, we've been requested to get bake objects, but `bake_influence_objects` is {}".format(bake_influence_objects))
            return []

        if not include_self:
            objects = [obj for obj in objects if obj != context.active_object]

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
        name = self.operator.color_layer_name
    
        if not mesh.vertex_colors or name not in mesh.vertex_colors:
            layer = mesh.vertex_colors.new()
            layer.name = name
    
            mesh.vertex_colors.active = layer
    
        layer = mesh.vertex_colors[name]
    
        return layer
    
    def get_vertex_group(self):
        """Returns Blender's `VertexGroup` object."""
        obj = self.active_object
        name = self.operator.group_name
    
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

                if self.operator.color_invert:
                    brightness = 1 - brightness
                
                loop_index = polygon.loop_indices[i]
                layer.data[loop_index].color = (brightness, brightness, brightness, 1.0)
    
    def apply_vertex_groups(self):
        """Apply `self.ao_data` to the vertex group."""
        group = self.get_vertex_group()
    
        for vertex_index in self.ao_data:
            weight = self.ao_data[vertex_index]
            
            if self.operator.weight_invert:
                weight = 1 - weight
                
            group.add([vertex_index], weight, "REPLACE")

    def start(self):
        print("Baking vertex AO...")
        
        operator = self.operator
        context = self.context
        
        depsgraph = context.evaluated_depsgraph_get()
    
        # The object to bake.
        self.active_object = context.active_object
    
        # Objects that we'll check AO on.
        self.bake_objects = BakeAO.get_bake_objects(context, operator.bake_influence_objects, operator.include_self)

        print("{} object(s) contributing to bake".format(len(self.bake_objects)))
    
        # Finally, get all the BVH tree objects from each object.
        self.bake_object_cache = [(BVHTree.FromObject(bake_obj, depsgraph), bake_obj.matrix_world.inverted()) for bake_obj in self.bake_objects]

        # The mesh we're baking from.
        self.active_mesh = self.active_object.data

        # Create a set of random samples. This dramatically speeds up baking.
        self.sample_distribution = []

        # Set our seed.
        np.random.seed(self.operator.seed)
    
        for i in range(operator.sample_count):
            self.sample_distribution.append(BakeAO.random_vector())

    def bake(self, vertices=-1):
        """Bakes `vertices` number of vertices. If `vertices` is negative, bakes to completion. This function should be called until it returns `True`."""
        operator = self.operator
        context = self.context
        mesh = self.active_mesh

        i = 0
        
        print("Calculating ambient occlusion... {:03.2f}%".format(self.get_progress_percentage()))
        
        for vertex in mesh.vertices[self.last_vertex_index:]:

            ao_vertex = self.calculate_vertex_ao(vertex)
    
            self.ao_data[vertex.index] = ao_vertex

            self.last_vertex_index += 1

            i += 1
            
            if vertices > 0 and i > vertices:
                return False

        print("Calculating ambient occlusion... 100%")
        return True


    def finish(self):
        operator = self.operator
        context = self.context

        if operator.bake_to_color:
            print("Applying ambient occlusion to vertex color layer '{}'".format(operator.color_layer_name))
            
            self.apply_vertex_colors()
            
        if operator.bake_to_group:
            print("Applying ambient occlusion to vertex group layer '{}'".format(operator.group_name))
            
            self.apply_vertex_groups()
    
        print("Done!")
        
class MESH_OT_bake_vertex_ao(bpy.types.Operator):
    bl_idname = "mesh.bake_vertex_ao"
    bl_label = "Bake Vertex Ambient Occlusion"
    bl_description = "Bakes ambient occlusion into vertex data for the active mesh"
    bl_options = {"BLOCKING", "UNDO", "PRESET"}

    # Influence
    
    bake_influence_objects: bpy.props.EnumProperty(
        name="Objects",
        description="Select which objects should contribute to ambient occlusion. Objects that are hidden in the viewport don't contribute",
        items=[
            ("scene", "Entire Scene", "Use all visible objects in the scene.", "SCENE_DATA", 0),
            ("selected", "Selected Objects", "Bakes occlusion from selected objects only.", "RESTRICT_SELECT_OFF", 1),
            ("active", "Active Object Only", "Bakes occlusion from active object only.", "OBJECT_DATA", 2),
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
            # Start the bake.
            self._bake = BakeAO(self, context)
        
        try:
            # Perform 10000 samples every time before updating.
            is_completed = self._bake.bake(10000 / self.sample_count)

            # Appears in the lower-left corner.
            self.update_status(context, "Baking vertex ambient occlusion: {:03.1f}%".format(self._bake.get_progress_percentage()))
            
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
        
        if exists:
            self.draw_warning_icon(box, "'{}' exists and will be overwritten".format(getattr(self, name_prop)))
        else:
            self.draw_checkmark_icon(box, "'{}' will be created".format(getattr(self, name_prop)))

        box.use_property_split = True
        row = box.column()
        row.prop(self, invert_prop)

    # Draws the primary UI.
    def draw(self, context):
        layout = self.layout
        
        layout.separator()

        layout.label(text="Contributing Objects:")
        
        row = layout.row(align=True)
        row.prop(self, "bake_influence_objects", text="")
        row.prop(self, "include_self", toggle=True, icon="OBJECT_DATA", text="")
        
        bake_objects = BakeAO.get_bake_objects(context, self.bake_influence_objects, self.include_self)
        layout.label(text="{} object{} contributing to ambient occlusion bake".format(len(bake_objects), "s" if len(bake_objects) != 1 else ""))

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

        total_sample_count = self.sample_count * len(context.active_object.data.vertices)

        layout.label(text="{:,} samples total".format(total_sample_count))

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
