#include <string>
#include "matplotlibcpp.h"


int main(){
    matplotlibcpp::figure_size(800,600);
    matplotlibcpp::plot({1,3,2,4,3,5});
    matplotlibcpp::title("Simple plot");
    matplotlibcpp::xlabel("x axis");
    matplotlibcpp::ylabel("y axis");
    matplotlibcpp::legend();
    matplotlibcpp::show();
    return 0;
}