use <gopro_mounts_mooncactus.scad>
include <write.scad>

// Create a "triple" gopro connector
translate([0,-10.5,0])
gopro_connector("double");

// Variables assume phone in portrait orientation, looking at screen
ph_height     = 147;
ph_width    = 74;
ph_thick     = 10;
wall			 = 2;
camera_hole_to_right_edge = 10;
camera_hole_to_top_edge = 10;
camera_hole_diameter = 20;
left_side_edge_to_screen = 10;
bottom_edge_to_screen = 10;
lift_holes_diameter= 15;
edge_cylinder_diameter=5;



color([0.6,0.6,0.6])
translate([-ph_thick/2,0,-ph_height/2])
difference (){
	//everything that should be printed
	union() {
		cube([ph_thick+wall*2,ph_width+wall*2,ph_height+wall*2]);
		//strengthening borders
		borders();
		translate([ph_thick+wall*2-wall,0,0]) borders();
	}
	//everything that shoudl be cut out
	union() {
		translate([wall,wall,wall])
		//phone body
		cube([ph_thick,ph_width+10,ph_height]);
		
		//camera hole
		hull() {
		translate([0,ph_width-camera_hole_to_right_edge,ph_height-camera_hole_to_top_edge]) {
			rotate([90,0,90])	{
				cylinder(3*wall,d=camera_hole_diameter,center=true);
				translate([-30,0,0]) cylinder(3*wall,d=camera_hole_diameter,center=true);
				translate([-30,-15,0]) cylinder(3*wall,d=camera_hole_diameter,center=true);
			}
		}
}
		//cutouts on the lower corners for easy push-out of the phone
		rotate([90,0,90])	cylinder(5*ph_thick,d=lift_holes_diameter,center=true);
		translate([0,0,ph_height+wall*2]) {
			rotate([90,0,90]) cylinder(5*ph_thick,d=lift_holes_diameter,center=true);
		}
		translate([wall*2+ph_thick/2,left_side_edge_to_screen,bottom_edge_to_screen]) cube([wall*6,ph_width*0.85,ph_height*0.9]);
		
		
		
	}
}

module borders() {
  	translate([wall/2,0,wall/2])rotate([0,90,90]) cylinder(ph_width+wall*2, d=edge_cylinder_diameter);
	translate([wall/2,wall/2,0]) cylinder(ph_height+wall*2, d=edge_cylinder_diameter);
	translate([wall/2,0,ph_height+wall*2-wall/2]) rotate([0,90,90]) cylinder(ph_width+wall*2, d=edge_cylinder_diameter);
}
