cmake_minimum_required(VERSION 3.0)

project(matplotlib_demo)

find_package(Python3 COMPONENTS Interpreter Development REQUIRED)


add_executable(matplotlib_demo main.cpp)

target_include_directories(matplotlib_demo PUBLIC ${PROJECT_SOURCE_DIR}/)

target_link_libraries(
    matplotlib_demo
    Python3::Python
    Python3::Module
    #${Python3_LIBRARIES}
)

install(TARGETS matplotlib_demo              #    安装可执行程序
        RUNTIME DESTINATION bin)             #    放到前缀下的 bin 目录
