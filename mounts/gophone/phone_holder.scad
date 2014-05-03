use <gopro_mounts_mooncactus.scad>
include <write.scad>

// Create a "triple" gopro connector
translate([0,-10.5,0])
gopro_connector("double");


ph_width     = 147;
ph_height    = 74;
ph_thick     = 9.5;
wall			 = 2;
camera_hole_to_top_edge = 11.5;
camera_hole_to_side_edge = 10;
camera_hole_diameter = 15;
side_edge_to_screen = 10;
bottom_edge_to_screen = 10;
lift_holes_diameter= 20;


color([0.6,0.6,0.6])
translate([-ph_thick/2,0,-ph_width/2])
difference (){
	union() {
		cube([ph_thick+wall*2,ph_height+wall*2,ph_width+wall*2]);

	}
	union() {
		translate([wall,wall,wall])
		//phone body
		cube([ph_thick,ph_height+10,ph_width]);
		
		//camera hole
		translate([0,ph_height-camera_hole_to_top_edge,ph_width-camera_hole_to_side_edge]) {
			rotate([90,0,90])	cylinder(3*wall,d=camera_hole_diameter,center=true);
		}

		rotate([90,0,90])	cylinder(30,d=lift_holes_diameter,center=true);
		translate([0,0,ph_width]) {
			rotate([90,0,90]) cylinder(30,d=lift_holes_diameter,center=true);
			translate([0, ph_height/2, -ph_height])
			rotate([270,270,90])
				write("Mapillary",h=10,t=wall/2,center=true);
		}
		translate([wall*2+ph_thick/2,side_edge_to_screen,bottom_edge_to_screen]) cube([wall*6,ph_height*0.8,ph_width*0.8]);
		
		
		
	}
}
