set(LORALAB_CODEC2_ROOT "${CMAKE_CURRENT_LIST_DIR}")
set(LORALAB_CODEC2_SOURCES
    "${LORALAB_CODEC2_ROOT}/codec2_dependency.c"
    "${LORALAB_CODEC2_ROOT}/generated/codebookd.c")
foreach(source codec2 codec2_fft interp kiss_fft kiss_fftr lpc lsp nlp pack phase postfilter quantise sine)
    list(APPEND LORALAB_CODEC2_SOURCES "${LORALAB_CODEC2_ROOT}/vendor/src/${source}.c")
endforeach()

function(loralab_codec2_configure target)
    target_include_directories(${target} PUBLIC "${LORALAB_CODEC2_ROOT}"
        PRIVATE "${LORALAB_CODEC2_ROOT}/vendor/src" "${LORALAB_CODEC2_ROOT}/generated")
    target_compile_definitions(${target} PRIVATE
        CODEC2_MODE_EN_DEFAULT=0 CODEC2_MODE_3200_EN=1 __EMBEDDED__
        codec2_malloc=malloc codec2_calloc=calloc codec2_free=free)
    target_compile_options(${target} PRIVATE
        -O2 -fno-fast-math -ffunction-sections -fdata-sections -fvisibility=hidden)
endfunction()
