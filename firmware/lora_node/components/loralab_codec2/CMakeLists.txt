include("${CMAKE_CURRENT_LIST_DIR}/core.cmake")
idf_component_register(SRCS ${LORALAB_CODEC2_SOURCES} INCLUDE_DIRS "."
    PRIV_INCLUDE_DIRS "vendor/src" "generated")
loralab_codec2_configure(${COMPONENT_LIB})
