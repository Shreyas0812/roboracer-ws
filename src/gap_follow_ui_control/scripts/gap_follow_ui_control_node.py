#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile

from roboracer_interfaces.msg import CarControlGapFollow
from std_msgs.msg import Float32
from sensor_msgs.msg import LaserScan

import numpy as np

class GapFollowUIControlNode(Node):
    def __init__(self):
        super().__init__("gap_follow_ui_control_node")
        self.get_logger().info("Gap Follow UI Control Node Started")

        self.throttle = 0.2
        self.window_half = 40
        self.disparityExtender = 50
        self.maxActionableDist = 2.0

        self.running_steering_angle = 0.0

        qos_profile = QoSProfile(depth=10)

        # Subscriber Topics
        gap_follow_params_sub_topic = "gap_follow_params"
        lidar_sub_topic = '/autodrive/f1tenth_1/lidar'

        self.gap_follow_params_sub_ = self.create_subscription(CarControlGapFollow, gap_follow_params_sub_topic, self.gap_follow_params_callback, qos_profile)
        self.lidar_sub_ = self.create_subscription(LaserScan, lidar_sub_topic, self.lidar_callback, qos_profile)

        # Publisher topics
        steering_pub_topic = '/autodrive/f1tenth_1/steering_command'
        throttle_pub_topic = '/autodrive/f1tenth_1/throttle_command'

        self.throttle_pub = self.create_publisher(Float32, throttle_pub_topic, qos_profile)
        self.steering_pub = self.create_publisher(Float32, steering_pub_topic, qos_profile)

    def gap_follow_params_callback(self, msg):
        if self.throttle != msg.throttle:
            self.throttle = msg.throttle 

        if self.window_half != msg.window_half_size:
            self.window_half = msg.window_half_size

        if self.disparityExtender != msg.disparity_extender:
            self.disparityExtender = msg.disparity_extender

        if self.maxActionableDist != msg.max_actionable_dist:
            self.maxActionableDist = msg.max_actionable_dist

    def get_range(self, range_data, angle):
        
        index = int((angle - range_data['angles'][0]) / range_data['angle_increment'])

        start_index = index - self.window_half
        end_index = index + self.window_half

        # average of 10 points around the index 
        return_range = np.average(range_data['ranges'][start_index:end_index])

        return index, return_range
    
    def find_best_point(self, start_i, end_i, range_data):
        """Start_i & end_i are start and end indicies of max-gap range, respectively
        Return index of best point in ranges
	    Naive: Choose the furthest point within ranges and go there
        """
        # Going to the center of the gap for now

        slow_turn1 = False
        slow_turn2 = False
        slow_turn3 = False

        running_towards_idx, running_towards_dist = self.get_range(range_data, self.running_steering_angle)

        center_point_idx = int((start_i + end_i) / 2)
        
        diff_in_index = np.abs(center_point_idx - running_towards_idx)

        if diff_in_index <= 5:
            slow_turn1 = True
        elif diff_in_index <= 10:
            slow_turn2 = True
        elif diff_in_index <= 15:
            slow_turn3 = True

        furthest_point_idx = center_point_idx

        return slow_turn1, slow_turn2, slow_turn3, furthest_point_idx

    def find_max_gap(self, free_space_ranges, gaps):
        """ Return the start index & end index of the max gap in free_space_ranges
        """

        if len(gaps) == 0:
            return (0, 1080)
        range_gap = []
        start = gaps[0]
        prev = gaps[0]

        for curr in gaps[1:]:
            if curr != prev + 1:
                range_gap.append((start, prev))
                start = curr
            prev = curr

        # Add the last range
        range_gap.append((start, prev))

        largest_range_gap = max(range_gap, key=lambda x: x[1] - x[0])

        return largest_range_gap
    
    def mutate_ranges(self, ranges, center_index, value):
        """ Mutate ranges to be a certain value
        """
        ranges[center_index-self.window_half:center_index+self.window_half] = value

        return ranges
    
    def preprocess_lidar(self, proc_ranges):
        """ Preprocess the LiDAR scan array. Expert implementation includes:
            1.Setting each value to the mean over some window
            2.Rejecting high values (eg. > 3m)
        """

        gaps = []
        for i in range(self.window_half, len(proc_ranges)-self.window_half):
            cur_mean = np.mean(proc_ranges[i-self.window_half:i+self.window_half+1])
            if cur_mean > self.maxActionableDist:
                gaps.append(i)

        for index in gaps:
            proc_ranges = self.mutate_ranges(proc_ranges, index, self.maxActionableDist)

        return proc_ranges, gaps
    
    def lidar_callback(self, data):
        """ Process each LiDAR scan as per the Follow Gap algorithm & publish an AckermannDriveStamped Message
        """

        range_data = {
            'ranges': np.array(data.ranges),
            'angles': np.linspace(data.angle_min, data.angle_max, len(data.ranges)),
            'angle_increment': data.angle_increment
        }

        dead_straight_idx, dead_straight = self.get_range(range_data, 0)

        proc_ranges, gaps = self.preprocess_lidar(range_data['ranges'])

        min_dist_idx = np.argmin(proc_ranges)

        #Decrease perceived distance in the bubble
        bubble_start = max(0, min_dist_idx - self.disparityExtender)
        bubble_end = min(len(proc_ranges), min_dist_idx + self.disparityExtender)

        proc_ranges[bubble_start:bubble_end] = proc_ranges[bubble_start:bubble_end] - 1.5

        # remove negative values
        proc_ranges[proc_ranges < 0] = 0

        # Remove the range values which correspond to the gap behind the car
        start_index = len(range_data['ranges']) // 6     # corresponds to -90 degrees
        end_index = (len(range_data['ranges']) * 5) // 6 # corresponds to +90 degrees
        proc_ranges[: start_index] = 0
        proc_ranges[end_index:] = 0

        # Adjusting Gaps
        gaps = list(set(gaps) - set(range(bubble_start, bubble_end+1)) - set(range(0, start_index)) - set(range(end_index, 1080)))

        start_idx, end_idx = self.find_max_gap(proc_ranges, gaps)        

        # Smooth turns
        slow_turn1, slow_turn2, slow_turn3, best_point = self.find_best_point(start_idx, end_idx, range_data)

        angle = range_data["angles"][0] + best_point * range_data["angle_increment"]
        
        if slow_turn1:
            angle = angle * 0.3
        elif slow_turn2:
            angle = angle * 0.4
        elif slow_turn3:
            angle = angle * 0.5

        #Publish Drive message
        self.running_steering_angle = angle

        self.publish_to_car(angle, self.throttle)

    def publish_to_car(self, steering_angle, throttle):
        """
        Publish the steering angle and throttle to the car.

        Args:
            steering_angle: Steering angle in radians
            throttle: Throttle value
        Returns:
            None
        """

        self.get_logger().info(f"Steering angle: {steering_angle}, Throttle: {throttle}", throttle_duration_sec=1.0)

        steering_angle = np.clip(steering_angle, -1, 1) # Limit steering angle to [-30, 30] degrees

        steering_msg = Float32()
        steering_msg.data = steering_angle 

        throttle_msg = Float32()
        throttle_msg.data = throttle 

        self.steering_pub.publish(steering_msg)
        self.throttle_pub.publish(throttle_msg)
    
def main(args=None):
    rclpy.init(args=args)
    node = GapFollowUIControlNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    main()