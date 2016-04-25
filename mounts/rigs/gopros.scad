use <../modules/gopro_mounts_mooncactus.scad>



total_width = 150;
base_thickness = 15;
screw_hole_distance = 70;


difference (){
	//everything that should be printed
	union() {
        color([1,0,0])
        translate([-total_width/2,-total_width/2, -base_thickness]) 
		cube([total_width,total_width, base_thickness]);
        union() {
            rotate([-90, 0, 0])
            for (angle=[0:90:360])
                rotate([0,angle,0])
                translate([0,-10, total_width/2-10])
                rotate([0,90,0])
                // Create a "triple" gopro connector
                gopro_connector("triple");
            
        }

	}
	//everything that should be cut out
	union() {
        for (angle=[0:90:360])
          rotate([-90, 0, 0])
          rotate([0,angle,0])
          translate([screw_hole_distance/2,-10, screw_hole_distance/2])
          rotate([-90, 0, 0])
              cylinder(r=8,h=60);
	}
}

