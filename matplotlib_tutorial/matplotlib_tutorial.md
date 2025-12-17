# matplotlib 快速上手（C++ 单头文件版）

本教程分两部分：  
1) **快速接入**：如何在你的 C++ 项目里用 `matplotlibcpp.h`（参考当前示例工程）。  
2) **常用接口**：日常画图最常见的函数速查。

## 1. 快速接入你的 C++ 项目

- 获取头文件：将 `matplotlibcpp.h` 放入项目（示例在 `project/sq_test/matplotlib/`）。
- CMake 依赖（核心几点）：
  ```cmake
  find_package(Python3 COMPONENTS Interpreter Development REQUIRED)

  add_executable(matplotlib_demo main.cpp)
  target_include_directories(matplotlib_demo PUBLIC ${PROJECT_SOURCE_DIR})
  target_link_libraries(matplotlib_demo
      Python3::Python
      Python3::Module
  )
  ```
  可选：安装了 NumPy 时，额外链接 `Python3::NumPy`，否则在代码里定义 `#define WITHOUT_NUMPY` 关闭相关功能。
- 编译运行：
  ```bash
  cd project/sq_test/matplotlib
  mkdir -p build && cd build
  cmake ..
  make -j
  ./matplotlib_demo
  ```
- 代码最小示例（同目录的 `main.cpp` 思路）：
  ```cpp
  #include "matplotlibcpp.h"
  namespace plt = matplotlibcpp;

  int main() {
      std::vector<double> x{0,1,2,3};
      std::vector<double> y{0,1,4,9};
      plt::plot(x, y, "r-");
      plt::xlabel("x");
      plt::ylabel("y");
      plt::title("demo");
      plt::show();
      return 0;
  }
  ```
- 运行环境提示：
  - 需要系统安装 Python3、`python3-dev`，可选 `python3-numpy`。
  - 没有显示环境时，可用 `plt::savefig("out.png")` 直接出图。

## 2. 常用接口速查

以命名空间 `namespace plt = matplotlibcpp;` 为前提：

- `plot(x, y, style)`：线图，`style` 如 `"r-"`、`"bo"`。
- `scatter(x, y, s, c)`：散点，`s` 点大小，`c` 颜色。
- `bar(x, heights, width)`：柱状图。
- `hist(data, bins)`：直方图。
- `imshow(matrix)`：显示矩阵/图像（需要 NumPy/OpenCV 支持更好）。
- `xlim(xmin, xmax)` / `ylim(ymin, ymax)`：轴范围。
- `xlabel("text")` / `ylabel("text")` / `title("text")`：标签与标题。
- `legend()`：显示图例（先在 `plot`/`scatter` 里传 `label="name"`）。
- `grid(bool)`：网格开关。
- `figure()` / `subplot(rows, cols, index)`：管理画布与子图。
- `savefig("file.png", dpi=150)`：保存图片，常用于无 GUI 环境。
- `show()`：显示窗口（需要可用的显示环境）。
- 性能/无头：大批量绘制或无显示时，建议多次绘制后统一 `savefig`，避免频繁 `show`。

就这些“口袋法术”足够日常可视化调试啦，拿来就能画，保持快乐！  
