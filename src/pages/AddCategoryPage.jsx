import React, { useState, useEffect } from "react";
import { useFirebase } from "../context/Firebase";

import "./Category.css";
import CustomIcon from "../components/CustomIcon";
import NavbarNew from "../components/NavbarNew";

function Category() {
  const firebase = useFirebase();
  const [categoryName, setCategoryName] = useState("");
  const [iconId, setIconId] = useState("");
  const [colorId, setColorId] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();

    try {
      const forCreatingCategory = await firebase.handleNewCategory(
        categoryName,
        iconId,
        colorId,
        firebase.user.uid
      );
      alert("Category added");
    } catch (error) {
      console.error("Error adding category:", error.message);
      alert("Failed to add category. Please try again.");
    }
  };

  const handleRadioChange = (e) => {
    console.log("Selected Radio Value:", iconId);
  };

  return (
    <div className="bg-slate-900 h-full sm:h-screen">
      <NavbarNew></NavbarNew>

      <div
        className="container flex flex-col justify-center items-center font-[Rubik] "
        onSubmit={handleSubmit}
      >
        <h2 className="text-white mb-4">Create Category</h2>

        <form className="max-w-[28rem] flex-col space-y-3">
          <div className="relative">
            <input
              type="text"
              id="floating_outlined1"
              className="block px-2.5 pb-2.5 pt-2.5 w-full text-md text-white bg-transparent rounded-lg border-2 border-slate-400 appearance-none focus:outline-none focus:ring-0 focus:border-blue-400 peer"
              placeholder=" "
              onChange={(e) => setCategoryName(e.target.value)}
            />

            <label
              htmlFor="floating_outlined"
              className="absolute text-slate-300 bg-slate-900 text-md duration-300 transhtmlForm -translate-y-4 scale-75 top-2 z-10 origin-[0]  px-2 peer-focus:px-2 peer-focus:text-blue-400 peer-placeholder-shown:scale-100 peer-placeholder-shown:-translate-y-1/2 peer-placeholder-shown:top-1/2 peer-focus:top-2 peer-focus:scale-75 peer-focus:-translate-y-4 rtl:peer-focus:translate-x-1/4 rtl:peer-focus:left-auto start-1"
            >
              Category Name
            </label>
          </div>

          <div>
            <label
              htmlFor="program-name"
              className="block mb-2 text-sm font-medium text-gray-900 dark:text-white"
            >
              Select Currency
            </label>

            <div
              className="radio-tile-group flex flex-wrap justify-center items-center"
              onChange={(e) => setIconId(e.target.value)}
            >
              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={1}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform">
                  <div className="w-6">
                    <CustomIcon icon={1}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={2}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={2}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={3}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={3}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={4}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={4}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={5}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={5}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={6}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={6}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={7}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={7}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={8}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={8}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={9}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={9}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={10}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={10}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={11}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={11}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={12}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={12}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={13}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={13}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={14}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={14}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={15}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={15}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={16}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={16}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={17}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={17}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={18}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={18}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={19}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={19}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={20}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={20}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={21}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={21}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={22}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={22}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={23}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={23}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={24}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={24}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={25}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={25}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={26}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={26}></CustomIcon>
                  </div>
                </div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative">
                <input
                  id="walk"
                  className="radio-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio"
                  value={27}
                />
                <div className="radio-tile flex flex-col items-center justify-center w-full h-full rounded-full p-4 transition-transform ">
                  <div className="w-6 fill-black">
                    <CustomIcon icon={27}></CustomIcon>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div>
            <label
              htmlFor="program-name2"
              className="block mb-2 text-sm font-medium text-gray-900 dark:text-white"
            >
              Select Currency
            </label>

            <div
              className="radio-tile-group flex flex-wrap justify-center items-center"
              onChange={(e) => setColorId(e.target.value)}
            >
              <div className="input-container h-12 w-12 m-2 relative bg-[#FD2741] rounded-full">
                <input
                  id="walk2"
                  className="color-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio2"
                  value={1}
                />
                <div className="color-tile flex flex-col items-center justify-center w-full h-full rounded-full transition-transform"></div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative bg-[#458FFF] rounded-full">
                <input
                  id="walk"
                  className="color-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio2"
                  value={2}
                />
                <div className="color-tile flex flex-col items-center justify-center w-full h-full rounded-full transition-transform"></div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative bg-[#FFA800] rounded-full">
                <input
                  id="walk"
                  className="color-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio2"
                  value={3}
                />
                <div className="color-tile flex flex-col items-center justify-center w-full h-full rounded-full transition-transform"></div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative bg-[#48BB45] rounded-full">
                <input
                  id="walk"
                  className="color-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio2"
                  value={4}
                />
                <div className="color-tile flex flex-col items-center justify-center w-full h-full rounded-full transition-transform"></div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative bg-[#BC58EB] rounded-full">
                <input
                  id="walk"
                  className="color-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio2"
                  value={5}
                />
                <div className="color-tile flex flex-col items-center justify-center w-full h-full rounded-full transition-transform"></div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative bg-[#F460C2] rounded-full">
                <input
                  id="walk"
                  className="color-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio2"
                  value={6}
                />
                <div className="color-tile flex flex-col items-center justify-center w-full h-full rounded-full transition-transform"></div>
              </div>

              <div className="input-container h-12 w-12 m-2 relative bg-[#FF810D] rounded-full">
                <input
                  id="walk"
                  className="color-button opacity-0 absolute top-0 left-0 h-full w-full cursor-pointer "
                  type="radio"
                  name="radio2"
                  value={7}
                />
                <div className="color-tile flex flex-col items-center justify-center w-full h-full rounded-full transition-transform"></div>
              </div>
            </div>
          </div>

          <div className="flex flex-col md:flex-row-reverse md:gap-2">
            <button
              type="submit"
              className="text-white w-full bg-blue-600 font-medium rounded-lg text-md px-5 py-2.5 text-center mb-2 transition-all duration-300 ease-in-out"
            >
              Submit
            </button>

            <a
              className="text-white w-full border-white border-2 font-medium rounded-lg text-md px-5 py-2.5 text-center  mb-2 transition-all duration-300 ease-in-out decoration-transparent"
              href="/"
            >
              Back to Home
            </a>
          </div>
        </form>
      </div>
    </div>
  );
}

export default Category;
