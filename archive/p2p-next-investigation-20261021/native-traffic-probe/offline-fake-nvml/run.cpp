#include "../nvml_sampler.h"
int main(){
 try{traffic::Client c;c.initialize();traffic::Sampler s(c);
 std::this_thread::sleep_for(std::chrono::milliseconds(200));s.stage(1);auto begin=traffic::now_ns();
 std::this_thread::sleep_for(std::chrono::milliseconds(240));auto end=traffic::now_ns();s.stage(2);
 std::this_thread::sleep_for(std::chrono::milliseconds(60));s.stop_join();
 return s.report(1,begin,end)?0:6;
 }catch(const std::exception&e){std::printf("FAKE_RUN_EXCEPTION reason=%s\n",e.what());return 27;}
}
