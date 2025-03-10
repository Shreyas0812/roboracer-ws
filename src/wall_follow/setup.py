from setuptools import find_packages, setup

package_name = 'wall_follow'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/wall_follow.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='shreyas',
    maintainer_email='raorane@seas.upenn.edu',
    description='TODO: Package description',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'wall_follow_node = wall_follow.wall_follow_node:main',
        ],
    },
)
